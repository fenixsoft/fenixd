"""存量归档批量回填车道（add-knowledge-atlas-maintenance D1；方案 B 修订
fix-knowledge-backfill-reconstruction：能力聚合全链蒸馏 + 史前复原）。

前置 SPEC ``add-knowledge-atlas`` 的蒸馏管线只挂在「归档动作」上，存量归档不会再
被归档一次。本车道把 ``spec/archive/`` 全部存量归档按**能力聚合**语义回填真相源：

- 链索引（``build_chain_index``）纯机械扫描：能力 → 触碰它的全部归档 delta 链
  （日期升序）；蒸馏单元从归档改为**能力**，每能力一次成文最终态页面（rev=链长、
  sources 全链、溯源按时间序），批次 = 域内能力集合（批 ≤20）——页间独立，
  批序与正确性解耦、可并行、断点按能力续跑；
- 进度台账 v2 ``.fenix/knowledge_backfill.jsonl`` 双维度条目：
  ``capability:<名>``（能力页蒸馏）与 ``adr:<归档名>``（归档 ADR 抽取），各自
  pending/distilled/failed，断点独立续跑；v1 归档粒度条目重入作废剔除；
- 首段「聚类自举 run」：读链索引能力全集，产出域骨架与 ``能力名 → 域`` 归位清单，
  并接入史前复原段（git 考古求差，未覆盖能力产史前页、已覆盖能力基线作链头）；
- 中段按域分批派发聚合蒸馏 run，每批经 ``validate_knowledge`` 全量校验（≤2 轮
  修正反馈）后 pathspec 限定提交；末段 ADR 抽取批次（读归档 design.md）；
- failed 批标 failed 并登记 todo.md，不阻塞后续批；两维度全部终态后收敛，产出
  汇报，车道幂等（收敛后重入零派发）。

依赖：``core.knowledge`` 的 ``validate_knowledge`` 与提交工具函数经延迟导入复用；
前置未合并时车道整体降级为单行日志跳过（fail-open）。回填期 ``core.knowledge``
派发漏斗经 ``ledger_has_pending``/``register_archive_pending`` 排队协作，写段另取
``knowledge-distill.lock``（与 ``DistillManager`` 同一把 flock，``spec/knowledge/``
单写者由机制保证；本模块顶层不 import ``core.knowledge``，反向导入不构成环）。

激活方式：一次性批量车道，合并后手工激活（Migration Plan）——
``python3 -m core.knowledge_backfill --project-root <主树>``；daemon 不自动挂载，
避免合并即烧十几个蒸馏 run。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import time
from datetime import datetime, timedelta
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Optional

from core.agent_env_keys import AGENT_RUN_BANNED_ENV_KEYS
# add-harness-adapter-layer 4.1：一次性 spawn 收编入口（回填 run）
from core.agent_runner.harness import (
    ENV_MODE_CLEAN,
    ClaudeAdapter,
    SpawnRequest,
)
from core.agent_runner.harness.one_shot import (
    OneShotCommunicateError,
    run_one_shot,
)
from core.fs_utils import atomic_write_text as _fs_atomic_write_text
from core.git_text import unquote_git_path
from core.timelib import now_local
from core.proc_utils import guard_killpg


# spawn 注入缝：run 内单测用 fake spawn 替身；生产用 _default_spawn（claude -p）。
SpawnFn = Callable[[str, str], str]

# 降级路径日志（对齐 core.knowledge / core.evolution 的 fenixd.<module> 命名）
logger = logging.getLogger("fenixd.knowledge_backfill")

# 批规模上限（spec：实现裁量建议 ≤20）
BATCH_SIZE_MAX = 20
# 校验违规回反馈修正轮数上限（对齐前置 SPEC 蒸馏收尾校验的 ≤2 轮）
MAX_FIX_ROUNDS = 2
# 单个蒸馏 run 硬超时（秒）
SPAWN_TIMEOUT_SECONDS = 3600

LEDGER_RELPATH = ".fenix/knowledge_backfill.jsonl"
DOMAIN_MAP_RELPATH = ".fenix/knowledge_backfill_domains.json"
REPORT_RELPATH = ".fenix/knowledge_backfill_report.md"
KNOWLEDGE_DIR = "spec/knowledge"
PROMPT_PATH = Path(__file__).parent / "knowledge_prompts" / "backfill.md"
# 史前复原（prehistoric bootstrap）：归档目录全部始于该日，此前为史前窗口
PREHISTORIC_PROMPT_PATH = Path(__file__).parent / "knowledge_prompts" / "prehistoric.md"
PREHISTORIC_UNTIL = "2026-09-02"
PREHISTORIC_JSON_RELPATH = ".fenix/knowledge_backfill_prehistoric.json"

# 台账终态
STATUS_PENDING = "pending"
STATUS_DISTILLED = "distilled"
STATUS_FAILED = "failed"


class _NullLogger:
    """logger 未装配时的静默兜底（fenixd logger 的 (component, message) 签名）。"""

    def info(self, *_args) -> None:  # pragma: no cover - 静默替身
        pass

    def warning(self, *_args) -> None:  # pragma: no cover
        pass

    def error(self, *_args) -> None:  # pragma: no cover
        pass


class _StdLoggerAdapter:
    """标准 ``logging.Logger`` → fenixd ``(component, message)`` 签名适配。

    run_backfill 的留痕调用形如 ``log.warning("knowledge", msg)``；标准 logger
    不能直接传入（component 会被当消息、message 当位置参数，message 含 ``%``
    时还会格式化报错）。main() 手工激活路径经本适配传入，使破坏性清理删除前
    告警、批次提交失败 fail-open 留痕对操作者可见。
    """

    def __init__(self, std: logging.Logger):
        self._std = std

    def info(self, component: str, message: str) -> None:
        self._std.info("%s: %s", component, message)

    def warning(self, component: str, message: str) -> None:
        self._std.warning("%s: %s", component, message)

    def error(self, component: str, message: str) -> None:
        self._std.error("%s: %s", component, message)


def load_knowledge_core():
    """延迟导入前置 SPEC 的 ``core.knowledge``；未合并/损坏时返回 None。

    任务 2.3 接线缝：车道对校验器与提交工具函数只 import 不复制，真实实现由
    前置 SPEC 合并后提供；单测经 sys.modules 注入替身覆盖接线。
    """
    try:
        from core import knowledge as mod  # noqa: PLC0415

        return mod
    except Exception:
        return None


def atomic_write_text(path: Path, text: str) -> None:
    """整文件原子回写：薄委托仓库收口单点 ``core.fs_utils.atomic_write_text``。

    本模块原自持 pid 后缀 tmp + os.replace 的弱版本——裸 write_text 截断
    重写在进程中途被打断会留半截文件（self_review 同款教训）；tmp 名掺入
    pid 解决无锁并发回写交替截断同一 tmp 再 replace 落盘交错/半旧内容
    （code-review a0df618ce06b）。但该版本无任何 fsync，而 core.knowledge/
    knowledge_audit 均 import 本函数写 pending 台账、todo.md 与审计状态/
    报告，掉电/SIGKILL 下最新写入无持久化保证，与仓库纪律相悖
    （code-review 9348b05556b1）；现统一到 fs_utils 的 mkstemp 唯一临时名
    （并发截断问题同被其唯一性覆盖）+ 内容 fsync + 权限修复 + 父目录
    fsync 纪律。

    签名沿用历史形态 ``(path, text) -> None``，既有 import 方
    （knowledge/knowledge_audit）零改动；fs_utils 的
    ``inherit_existing_mode`` 参数不在本门面暴露，沿用其缺省口径
    （新文件 chmod 0644），需继承既有权限的调用方直接 import core.fs_utils。
    """
    _fs_atomic_write_text(path, text)


@contextmanager
def _todo_write_lock(project_root: Path):
    """todo.md 读改写窗口的进程间互斥（flock，``.fenix/.todo.md.lock``）。

    todo.md 的追加是「读全文→拼接→整文件回写」，两个写者同时读旧文本再
    各自回写时后写者会覆盖先写者的行；蒸馏重试台账与回填/审计车道共用
    本锁串行化该窗口（code-review 1bb1eacf2463）。锁文件名与其他 todo.md
    写方同一把——evolution._with_lock 对 ``todo.md`` 派生 ``.<name>.lock``、
    self_review._append_todo 与 code_fix 失败批追加均持该伴生锁；若本车道
    另立锁名，两簇锁互不互斥，跨车道并发仍是「各自读旧全文→拼接→原子
    替换」的后写覆盖先写（code-review 7508274d893d）。锁文件自身无内容语义。
    """
    import fcntl

    todo_dir = Path(project_root) / ".fenix"
    todo_dir.mkdir(parents=True, exist_ok=True)
    # [fenix-ignore:7508274d893d] 条目描述的另立锁名 todo.lock 在当前代码中不存在：锁文件已与其他 todo.md 写方统一为 .fenix/.todo.md.lock（见 docstring）
    fh = open(todo_dir / ".todo.md.lock", "w")  # noqa: SIM115 — 生命周期=with
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def _todo_subsection_insert(lines: list[str], subsection: str, item: str) -> list[str]:
    """把 ``item`` 归位插入今日日期节（``## YYYY-MM-DD``）的小节下（原位修改
    并返回 ``lines``）；日期节缺失时在文件尾部新建。今日节边界 = 下一个
    ``## `` 日期节或文件尾。"""
    today = time.strftime("%Y-%m-%d")
    today_idx = next((i for i, ln in enumerate(lines) if ln.strip() == f"## {today}"), None)
    if today_idx is None:
        lines += ["", f"## {today}", subsection, item]
        return lines
    end = next(
        (i for i in range(today_idx + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    block = lines[today_idx:end]
    sub_idx = next((i for i, ln in enumerate(block) if ln.strip() == subsection), None)
    if sub_idx is None:
        lines[today_idx:end] = block + [subsection, item]
    else:
        block.insert(sub_idx + 1, item)
        lines[today_idx:end] = block
    return lines


def append_todo_line(project_root: Path, line: str) -> bool:
    """向项目 ``.fenix/todo.md`` 追加一条待办（幂等：同文本已存在则跳过）。

    归位到今日日期节（``## YYYY-MM-DD``）下的「### 知识真相源」小节；日期节缺失
    时在文件尾部新建。给人看的队列，不进任务门禁（对齐前置 SPEC D3 口径）。
    读改写全程持 ``_todo_write_lock`` + ``atomic_write_text`` 原子回写。

    实际追加（幂等去重未命中、原子回写完成）后对 todo.md 就地 commit+push
    （ADR-060 写入点即时提交：tracked 的未提交改动滞留主树，会与分支的
    todo.md 改动路径重叠，被 merge-back WIP 重叠闸门拦截、烧 admin 车道
    代提交——2026-09-30 / 2026-10-13 两次同链事故）。提交动作在 flock 释放
    之后执行（git 子命令不进锁内临界区）；todo.md 未被 git 跟踪（含非 git
    仓库）跳过提交，commit/push 失败降级日志，均不阻断写路径、不向调用方
    抛错。
    """
    # 多行输入先归一为单行（spawn 失败的 stderr 尾部/失败归因 tail 天然多行）：
    # 幂等判定按整行精确比较，含换行的 line 使 f"- {line}" 跨多个物理行、与
    # splitlines() 的任何单行都不可能相等，同一失败会每次重复追加；且多行内容
    # 经 block.insert 拼回后会被下方按行解析日期节/小节结构的逻辑误当结构行
    # 处理（code-review d7bd04860ab6）
    line = re.sub(r"\s*\n\s*", " ", line).strip()
    todo_path = Path(project_root) / ".fenix" / "todo.md"
    with _todo_write_lock(project_root):
        text = todo_path.read_text(encoding="utf-8", errors="replace") if todo_path.exists() else ""
        # 幂等判定逐行精确比较（落盘形态为 "- {line}"）：子串包含会把前缀重叠
        # 的不同待办（动态尾串差异）误判为已存在而吞掉（code-review 599700eee421）
        if f"- {line}" in text.splitlines():
            return False
        lines = _todo_subsection_insert(text.splitlines(), "### 知识真相源", f"- {line}")
        atomic_write_text(todo_path, "\n".join(lines).rstrip("\n") + "\n")
    # 提交在锁外：git 子命令不进 flock 临界区，避免拉长持锁窗口阻塞 code_fix /
    # self_review 的并发追加（与 write_todo_marker 同款约束）
    _commit_todo_after_write(project_root, line)
    return True


def _append_todo_fail_open(project_root: Path, line: str, log) -> None:
    """``append_todo_line`` 的 fail-open 封装（run_backfill 失败分支留痕专用）。

    append_todo_line 自身只对提交/推送降级（``_commit_todo_after_write``），
    持锁、读 todo.md 与原子回写阶段的 OSError 会向外抛；失败分支调用它本意是
    留痕后 fail-open 返回，.fenix 只读/磁盘满等二次 OSError 会替换既定返回、
    以未处理异常掀翻车道。此处捕获 OSError 降级为日志留痕（对齐
    ``register_archive_pending`` 的容错口径），todo 留痕失败不掩盖原失败。
    """
    try:
        append_todo_line(project_root, line)
    except OSError as e:
        log.warning("knowledge", f"回填 todo 待办追加失败（fail-open）：{e}")


def upsert_todo_line(
    project_root: Path,
    prefix: str,
    line: str,
    cleanup_prefixes: tuple[str, ...] = (),
) -> bool:
    """同前缀 upsert 待办（add-knowledge-audit-escalation-consumption 1.3）。

    todo.md 中已存在以 ``prefix`` 开头的行（或 ``cleanup_prefixes`` 任一前缀的
    历史行）时收敛为单条 ``line``：整行替换、首条匹配行原位落点，多条历史行
    一并清理；不存在时按 append_todo_line 同款归位追加。``line`` 为空串时纯
    清理（只删不补——聚合对象清零后摘除残留行）。

    动态内容（如逐日推进的龄期）会改变行尾可变段：append_todo_line 的整行精确
    比较幂等对它失效（每天追加新行，聚合行自身变成每日重述），固定前缀匹配 +
    整行替换才保证「行内容变化时替换而非追加」。读改写全程持 ``_todo_write_lock``
    + ``atomic_write_text`` 原子回写；返回是否发生实际写盘。

    实际写盘（新增/整行替换/清理，返回 True）后经 ``_commit_todo_after_write``
    同款就地提交（返回值即提交开关，零写盘路径提前返回不提交）；提交动作同样
    在 flock 释放之后执行，降级口径与 append_todo_line 一致。
    """
    prefix = prefix.strip()
    if not prefix:
        raise ValueError("upsert_todo_line: prefix 不能为空")
    all_prefixes = tuple(
        dict.fromkeys((prefix, *(p.strip() for p in cleanup_prefixes if p.strip())))
    )
    line = re.sub(r"\s*\n\s*", " ", line).strip()
    todo_path = Path(project_root) / ".fenix" / "todo.md"
    with _todo_write_lock(project_root):
        text = todo_path.read_text(encoding="utf-8", errors="replace") if todo_path.exists() else ""
        # 落盘形态为 "- {内容}"，前缀匹配对齐该形态
        match_idx = [
            i
            for i, ln in enumerate(text.splitlines())
            if any(ln.startswith(f"- {p}") for p in all_prefixes)
        ]
        if not match_idx and not line:
            return False  # 纯清理但无残留行：零写盘
        lines = text.splitlines()
        first = match_idx[0] if match_idx else None
        if (
            len(match_idx) == 1
            and line
            and lines[first] == f"- {line}"
        ):
            return False  # 同前缀单行且内容未变：幂等零写盘
        for i in reversed(match_idx):
            del lines[i]
        if line:
            item = f"- {line}"
            if first is not None:
                lines.insert(first, item)
            else:
                lines = _todo_subsection_insert(lines, "### 知识真相源", item)
        atomic_write_text(todo_path, "\n".join(lines).rstrip("\n") + "\n")
    # 提交在锁外（同 append_todo_line）：走到这里即发生实际写盘；纯清理
    # （line 为空）时来源摘要回退到前缀，git log 仍可对账到被清理的待办
    _commit_todo_after_write(project_root, line if line else f"{prefix} 残留清理")
    return True


def _todo_commit_subject(source: str) -> str:
    """构造 todo.md 就地提交的固定主题行（``[fenix] todo: <来源摘要>``）。

    与 ``self_review._commit_todo`` 的 ``[fenix] daily self-review``、
    write_todo_marker 的 ``[fenix] evolution:`` 主题行同族，git log 可对账；
    来源摘要取写入内容归一化空白后的首段（截 60 字符），空来源兜底为通用
    文案（防御式，正常写路径不会走到）。
    """
    snippet = re.sub(r"\s+", " ", source or "").strip()[:60]
    return f"[fenix] todo: {snippet}" if snippet else "[fenix] todo: todo.md 回写"


def _commit_todo_after_write(project_root: Path, source: str) -> bool:
    """todo.md 实际写盘后的就地提交（add-todo-append-commit-on-write 1.1/1.4）。

    延迟导入复用 ``core.evolution._commit_todo_marker``（LC_ALL=C、git 子命令
    30s 超时、pathspec 限定 ``git commit -- .fenix/todo.md``、untracked/非 git
    仓库跳过、push 失败降级 WARNING 不重试），``subject=`` 传本车道主题行；
    evolution 顶层仅依赖 core.fs_utils/core.timelib（无本模块/knowledge 顶层
    依赖），延迟导入无循环依赖。MUST 在 ``_todo_write_lock`` 释放之后调用——
    git 子命令不进锁内临界区。任何异常降级日志留痕，不向调用方抛错（最坏
    情形回到「未提交改动滞留 → 闸门保守拦截」，不劣于提交前现状）。
    """
    try:
        from core.evolution import _commit_todo_marker  # noqa: PLC0415

        return _commit_todo_marker(project_root, subject=_todo_commit_subject(source))
    except Exception as e:  # noqa: BLE001 —— 提交失败不阻断写路径、不向调用方抛错
        logger.warning(
            "knowledge_backfill: todo.md 就地提交异常（降级留痕，写入不回滚）: %s", e
        )
        return False


# ── git 工具（pathspec 限定提交，主树直跑） ─────────────────────────────


def _git(project_root: Path, *args: str) -> str:
    # encoding/errors 固化（对齐 core.knowledge._git，code-review 383ecbbb8927）：
    # 裸 text=True 走 locale strict 解码，git 输出含非 UTF-8 字节（quotePath
    # 转义覆盖不了的畸形文件名字节等）时抛 UnicodeDecodeError（ValueError 而
    # 非 OSError），穿透 commit_pathspec / first_commit_ref 调用方捕获口径。
    proc = subprocess.run(
        ["git", *args],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} 失败: {proc.stderr.strip()[:300]}")
    return proc.stdout


def commit_pathspec(project_root: Path, paths: list[str], message: str) -> bool:
    """pathspec 限定提交：只提交 ``paths`` 内改动，不碰工作区他物。无改动返回 False。"""
    project_root = Path(project_root)
    status = _git(project_root, "status", "--porcelain", "--", *paths)
    if not status.strip():
        return False
    _git(project_root, "add", "--", *paths)
    _git(project_root, "commit", "-m", message, "--", *paths)
    return True


def _decode_git_quoted_path(rel: str) -> str:
    """解码 git porcelain 引号路径（C 风格转义）为盘上真实路径。

    git 对含双引号/控制字符等特殊字符的路径输出 ``"..."`` 引号串并转义内部
    字符（``\\"``、``\\\\``、``\\t`` 等短转义与 ``\\NNN`` 八进制字节转义）；
    只剥外层引号会把转义序列留在字面量里，得到的 relpath 与盘上真实路径
    不一致——该文件既回滚不掉也不计入 touched（code-review 36eb21ca1661 /
    38ce9b967142）。反转义与解码口径已统一收敛到 ``core.git_text``（与
    mergeback 的 ``_unquote_git_path`` 同一实现，code-review 3e99a584fdf5），
    本函数保留为薄委托以维持既有调用点命名。
    """
    return unquote_git_path(rel)


def _knowledge_dirty_files(project_root: Path) -> set[str]:
    """``spec/knowledge/`` 内未提交改动的 relpath 集合（tracked 改动 + 未跟踪
    新增，未跟踪目录以整体目录条目出现）。

    差集回滚的基线/现状快照共用单实现（knowledge_audit 亦 import 本函数，
    code-review b2e9ede6adec / 36eb21ca1661）；git 不可用/超时 fail-open
    返回空集。
    """
    try:
        proc = subprocess.run(
            [
                "git",
                "-c",
                "core.quotepath=false",
                "status",
                "--porcelain",
                "--",
                KNOWLEDGE_DIR,
            ],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            # errors="replace"：locale strict 解码遇非 UTF-8 文件名字节会抛
            # UnicodeDecodeError（OSError/TimeoutExpired 接不住，且本函数在
            # run_backfill 批次 try 之外，异常会掀翻整轮回填）；字节级反转义
            # 的 _decode_git_quoted_path 按 replace 后文本仍可工作，仅畸形
            # 路径的回滚精度受损
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    if proc.returncode != 0:
        return set()
    files: set[str] = set()
    for ln in proc.stdout.splitlines():
        if len(ln) <= 3:
            continue
        rel = ln[3:].strip()
        if " -> " in rel:  # 重命名条目取新路径
            rel = rel.split(" -> ", 1)[1]
        if len(rel) >= 2 and rel[0] == '"' and rel[-1] == '"':
            # 引号包裹的特殊字符路径：反转义还原真实 relpath
            rel = _decode_git_quoted_path(rel)
        else:
            rel = rel.strip('"')
        if rel:
            files.add(rel)
    return files


def discard_paths(project_root: Path, rels: list[str], log=None) -> None:
    """只回滚指定文件（tracked restore 逐路径 + 未跟踪批量 clean），不碰
    工作区其他改动。

    差集回滚口径的单实现（code-review 0f0f5941025c）：knowledge_audit 的
    语义转写失败回滚与本车道 ``discard_knowledge_changes`` 的 before 差集
    回滚共用本原语，超时值/restore 粒度不再各自演进。restore 逐路径执行：
    pathspec 混入未跟踪新路径时整条命令会一起失败（git restore 只要有一个
    pathspec 不匹配即整体报错，同条 tracked 文件也一并不被还原）。git 不可
    用/超时 fail-open；命令非零退出（pathspec 不匹配/索引锁冲突等）同样不
    抛错，收集失败路径统一 WARNING 留痕（code-review 0f075b2bce72）——回
    滚失败的内容仍在盘上，由本告警与调用方的 leftover 告警/待人工路径曝光，
    不阻塞调用方收尾。
    """
    if not rels:
        return
    log = log or _NullLogger()
    failed: list[str] = []
    clean_err = ""
    clean_ok = False
    for rel in rels:
        try:
            proc = subprocess.run(
                ["git", "restore", "--", rel],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                # encoding/errors 固化（对齐 _git / _knowledge_dirty_files）：
                # 裸 text=True 走 locale strict 解码，非 UTF-8 路径字节会使
                # UnicodeDecodeError（ValueError）穿透下方 except 口径
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        else:
            if proc.returncode != 0:
                # 本路径未还原：留痕待人工，不中断其余路径的回滚
                failed.append(rel)
    try:
        proc = subprocess.run(
            ["git", "clean", "-qfd", "--", *rels],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            # 同上：固化 UTF-8 解码，防非 UTF-8 文件名字节解码异常穿透 fail-open
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    else:
        if proc.returncode != 0:
            # clean 整体失败时未跟踪残留全部未清、无法细化到单路径，全量留痕
            failed.extend(rels)
            clean_err = proc.stderr.strip()[:200]
        else:
            clean_ok = True
    if failed and clean_ok:
        # 复核盘上残留（code-review 24c92bd4e926）：未跟踪新路径的 restore 必
        # 然非零（pathspec 不匹配整条报错），但这批路径若已被上面成功的 clean
        # 清除就不再滞留——按盘上事实过滤 failed，仅仍有残留的才告警，避免对
        # 未跟踪产出的每次回滚都发与盘面相反的误导告警；clean 失败/不可用/超
        # 时（clean_ok=False）时盘面复核不可信，维持全量留痕。
        failed = [
            rel
            for rel in failed
            if os.path.lexists(str(Path(project_root) / rel))
        ]
    if failed:
        log.warning(
            "knowledge",
            "回滚半失败留痕（fail-open 不抛错）：以下路径 restore/clean 返回"
            "非零，可能仍滞留 spec/knowledge/，请人工核查："
            + ", ".join(sorted(set(failed))[:10])
            + (f"（clean stderr：{clean_err}）" if clean_err else ""),
        )


def discard_knowledge_changes(
    project_root: Path,
    before: Optional[set[str]] = None,
    log=None,
) -> None:
    """放弃本次产出：只回滚本车道触达的文件（不留半成品，对齐前置 SPEC 蒸馏
    放弃语义）。只动 ``spec/knowledge/``，不碰他物。

    基线感知差集回滚（对齐 core.knowledge._discard_output 口径；restore/clean
    原语经 discard_paths 与 knowledge_audit 单实现共用，code-review
    b2e9ede6adec / 0f0f5941025c）：``before`` 为本段 run 前的脏文件快照，只对
    快照中不存在的新增脏路径 restore/clean；
    当前仍脏且基线已有的路径疑似用户未提交的手工策展与本车道产出同文件
    交织、无法安全拆分，降级 WARNING 留痕交人工核查，不再整目录连带回滚。
    ``before`` 缺省（旧调用口径）退回整目录回滚，可能吞掉用户未提交改动，
    仅作兜底保留。
    """
    project_root = Path(project_root)
    log = log or _NullLogger()
    if before is not None:
        after = _knowledge_dirty_files(project_root)
        overlap = sorted(after & before)
        if overlap:
            log.warning(
                "knowledge",
                "回填失败回滚：spec/knowledge/ 下存在 run 前已有且当前仍脏的路径"
                "（疑似用户未提交的手工策展，与本车道产出同文件无法安全拆分），"
                "保留不回滚，请人工核查：" + ", ".join(overlap[:5]),
            )
        rels = sorted(after - before)
        if not rels:
            return
        discard_paths(project_root, rels, log=log)
        return
    kdir = project_root / KNOWLEDGE_DIR
    # 兜底分支与 discard_paths 同款 fail-open：git 不可用/超时不以
    # OSError/TimeoutExpired 沿调用链上抛，留痕告警交人工核查
    # （code-review 514b88161b35）。
    # [fenix-ignore:514b88161b35] 条目指向的裸 subprocess.run 在当前代码中不存在：兜底分支已包 try/except (OSError, TimeoutExpired) 并留痕告警 fail-open（见上注）
    try:
        subprocess.run(
            ["git", "restore", "--", KNOWLEDGE_DIR],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            # encoding/errors 固化（对齐 _git）：防非 UTF-8 字节解码异常
            # 穿透 except (OSError, TimeoutExpired) 捕获口径
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        if kdir.is_dir():
            subprocess.run(
                ["git", "clean", "-qfd", "--", KNOWLEDGE_DIR],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                # 同上：固化 UTF-8 解码，防解码异常穿透 fail-open 捕获口径
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
    except (OSError, subprocess.TimeoutExpired):
        log.warning(
            "knowledge",
            "回填失败回滚（旧口径整目录兜底）：git restore/clean 不可用或超时，"
            "spec/knowledge/ 下本次产出未回滚，请人工核查",
        )


def resolve_commit(core) -> Callable[[Path, list[str], str], bool]:
    """提交工具接线（任务 2.3）：优先取 ``core.commit_knowledge``——该属性
    仅由单测经 sys.modules 注入替身时存在（测试接缝），core.knowledge 本体
    只提供私有 ``_commit_output``（签名与语义均不同），生产路径恒走回退的
    车道内 pathspec 提交实现。若未来 core.knowledge 落地同名公开函数，须先
    对齐本车道语义（返回值 bool 化：True=已提交 / False=无改动；失败显式
    抛错而非静默返回 None），否则会静默切换提交行为。"""
    fn = getattr(core, "commit_knowledge", None)
    if callable(fn):

        def _committed(project_root: Path, paths: list[str], message: str) -> bool:
            return bool(fn(project_root, paths, message))

        return _committed
    return commit_pathspec


# ── 进度台账（v2 双维度：capability / adr） ──────────────────────────────

# 台账条目键维度前缀（方案 B：能力页蒸馏与归档 ADR 抽取双维度正交）
CAPABILITY_PREFIX = "capability:"
ADR_PREFIX = "adr:"


def _is_v2_key(key: str) -> bool:
    return key.startswith((CAPABILITY_PREFIX, ADR_PREFIX))


# [fenix-ignore:783148c7ec9e] 本地朴素时间是有意取舍：updated_at 仅在本机 save() 合并中做字典序比较（同机同tz），若改用 timelib to_storage(now_utc()) 的 UTC/Z 后缀格式，同一时刻的新写入会比盘上既有 naive 本地串（UTC+8）字典序落后 8 小时，mark() 更新在按条合并（entry.updated_at >= other.updated_at）中永久落败、格式永远无法迁移，属行为回归故维持现状。
def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


@contextmanager
def _ledger_write_lock(project_root: Path):
    """回填台账读改写窗口的进程间互斥（flock，``.fenix/knowledge_backfill.lock``）。

    台账是整文件读改写语义：回填车道（run_backfill 多处整文件回写）与派发
    漏斗（register_archive_pending，daemon 进程）分属不同进程，无互斥时后写者
    会用内存中的旧 entries 覆盖先写者刚落盘的条目（code-review 5feb371288c8）。
    锁文件自身无内容语义。
    """
    import fcntl

    lock_dir = Path(project_root) / ".fenix"
    lock_dir.mkdir(parents=True, exist_ok=True)
    fh = open(lock_dir / "knowledge_backfill.lock", "w")  # noqa: SIM115 — 生命周期=with
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


class BackfillLedger:
    """回填进度台账 v2（``.fenix/knowledge_backfill.jsonl``，双维度条目）。

    条目键带维度前缀：``capability:<能力名>``（能力页聚合蒸馏）与
    ``adr:<归档名>``（该归档 design.md 的 ADR 抽取扫描），各自
    pending/distilled/failed，断点重入按维度独立续跑；收敛汇报分维度计数。
    v1 归档粒度条目（无前缀键）重入即作废剔除、v2 条目保留——台账是运行时
    进度非数据资产，无迁移负担（design D2）；作废只针对非 v2 键本身，单条
    v1 残留/误编辑行不再连带清空全部进度（code-review 5a5fe210d316）。
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: dict[str, dict[str, Any]] = {}
        self.legacy_discarded = False
        # load 时被作废剔除的 v1 旧格式键（留痕用，run_backfill 告警后随下次
        # save 从盘上清除）
        self.legacy_keys: list[str] = []

    @classmethod
    def load(cls, path: Path) -> "BackfillLedger":
        ledger = cls(path)
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue  # 损坏行跳过，不阻塞重入
                name = entry.get("name")
                if name:
                    ledger.entries[name] = entry
        # v1 残留只作废非 v2 键本身、保留 v2 条目：单条 v1 误编辑/残留行不再
        # 连带清空全部 distilled 进度，令数十个 run 的成果为一行脏数据买单
        # （code-review 5a5fe210d316）
        stale = sorted(k for k in ledger.entries if not _is_v2_key(k))
        for k in stale:
            del ledger.entries[k]
        if stale:
            ledger.legacy_discarded = True
            ledger.legacy_keys = stale
        return ledger

    def _new_entry(self, key: str) -> dict[str, Any]:
        return {"name": key, "status": STATUS_PENDING, "batch": None, "updated_at": _now()}

    def reconcile(
        self,
        chain_index: dict[str, list[str]],
        archive_names: list[str],
    ) -> list[str]:
        """补登双维度新条目（pending）：能力维度来自链索引键集，adr 维度来自
        全部归档名。返回本次新登键名单。已终态条目不动。"""
        fresh: list[str] = []
        for cap in sorted(chain_index):
            key = CAPABILITY_PREFIX + cap
            if key not in self.entries:
                self.entries[key] = self._new_entry(key)
                fresh.append(key)
        for name in sorted(archive_names):
            key = ADR_PREFIX + name
            if key not in self.entries:
                self.entries[key] = self._new_entry(key)
                fresh.append(key)
        return fresh

    def mark(self, key: str, status: str, batch: Optional[int] = None) -> None:
        entry = self.entries.get(key)
        if entry is None:
            entry = {"name": key, "status": status, "batch": batch}
            self.entries[key] = entry
        entry["status"] = status
        if batch is not None:
            entry["batch"] = batch
        entry["updated_at"] = _now()

    def reset_pending(self, key: str) -> bool:
        """终态条目重置为 pending（回填期新归档触碰已蒸馏能力后重新聚合）。

        Returns:
            是否发生重置（已是 pending 时为 False）。
        """
        entry = self.entries.get(key)
        if entry is not None and entry.get("status") == STATUS_PENDING:
            return False
        self.mark(key, STATUS_PENDING)
        return True

    def pending_keys(self) -> list[str]:
        """未终态条目键（重入只处理 pending 与 failed）。"""
        return [
            key
            for key, e in sorted(self.entries.items())
            if e.get("status") in (STATUS_PENDING, STATUS_FAILED)
        ]

    def pending_capabilities(self) -> list[str]:
        """能力维度未终态条目的能力名（不含前缀）。"""
        return [
            k[len(CAPABILITY_PREFIX):]
            for k in self.pending_keys()
            if k.startswith(CAPABILITY_PREFIX)
        ]

    def pending_adr_archives(self) -> list[str]:
        """ADR 维度未终态条目的归档名（不含前缀）。"""
        return [
            k[len(ADR_PREFIX):]
            for k in self.pending_keys()
            if k.startswith(ADR_PREFIX)
        ]

    def has_pending(self) -> bool:
        """是否存在 pending 条目（回填期排队门判据；failed 不阻塞排队门——
        failed 已登记 todo 待人工重试，不永久卡死增量派发）。"""
        return any(e.get("status") == STATUS_PENDING for e in self.entries.values())

    def counts(self) -> dict[str, dict[str, int]]:
        """分维度计数（收敛汇报口径）。"""
        out = {
            "capability": {STATUS_PENDING: 0, STATUS_DISTILLED: 0, STATUS_FAILED: 0},
            "adr": {STATUS_PENDING: 0, STATUS_DISTILLED: 0, STATUS_FAILED: 0},
        }
        for key, e in self.entries.items():
            dim = "capability" if key.startswith(CAPABILITY_PREFIX) else "adr"
            status = e.get("status", STATUS_PENDING)
            out[dim][status] = out[dim].get(status, 0) + 1
        return out

    def save(self) -> None:
        """整文件回写台账（读改写全程持进程间文件锁 + 按条合并）。

        回填 run 长跑期间派发漏斗（``register_archive_pending``，另一进程）会
        并发登记/重置条目；原子回写只保证单次写不撕裂，不保证读改写原子性，
        后写者会用内存中的旧 entries 整体覆盖先写者刚落盘的条目。持锁重读盘上
        最新条目后按条合并：仅一方持有的键直接纳入，两方都有的键取
        ``updated_at`` 较新的一方——新登记条目与 pending 重置不再被覆盖丢失。
        """
        with _ledger_write_lock(self.path.parent.parent):
            merged = dict(BackfillLedger.load(self.path).entries)
            for name, entry in self.entries.items():
                other = merged.get(name)
                if (
                    other is None
                    or str(entry.get("updated_at", "")) >= str(other.get("updated_at", ""))
                ):
                    merged[name] = entry
            self.entries = merged
            lines = [
                json.dumps(self.entries[name], ensure_ascii=False)
                for name in sorted(self.entries)
            ]
            atomic_write_text(self.path, "\n".join(lines) + ("\n" if lines else ""))


# ── 回填期排队（core.knowledge 派发漏斗调用，design D3） ─────────────────


def ledger_has_pending(project_root: Path) -> bool:
    """回填台账是否存在 pending 条目（增量派发排队门判据）。

    台账文件缺失 / 全部终态 → False（收敛后恢复即时派发）。v1 旧格式条目在
    load 即作废（视为无 pending），回填激活后按 v2 重建。
    """
    path = Path(project_root) / LEDGER_RELPATH
    if not path.exists():
        return False
    try:
        ledger = BackfillLedger.load(path)
    except (OSError, ValueError):
        return False
    return ledger.has_pending()


def register_archive_pending(project_root: Path, archive_name: str) -> bool:
    """把回填期新到的归档登记进台账（排队门触发时由派发漏斗调用）。

    - ``adr:<归档名>``：新条目置 pending（该归档的 ADR 抽取交回填车道）；
    - 该归档触碰的每个能力（``specs/`` 目录名）：条目已为终态的**重置为
      pending**——链索引重扫纳入新归档 delta 后重新聚合，否则新归档的溯源行
      永不落页；条目不存在则新建 pending。

    台账在盘、原子回写，重启安全；回写经 ``BackfillLedger.save`` 的进程间文件锁
    + 按条合并落盘，与回填 run 的并发整文件回写互斥、不互相覆盖。台账/specs
    目录不可读时 fail-open 返回 False 并登记 todo（对齐 ``ledger_has_pending``
    口径），不阻断派发漏斗。
    Returns: 是否发生登记/重置。
    """
    root = Path(project_root)
    try:
        ledger = BackfillLedger.load(root / LEDGER_RELPATH)
        specs = root / "spec" / "archive" / archive_name / "specs"
        caps = (
            sorted(p.name for p in specs.iterdir() if p.is_dir())
            if specs.is_dir()
            else []
        )
    except (OSError, ValueError):
        # 台账/归档 specs 在盘但不可读（权限/EIO/坏字节）时 fail-open 零动作
        # 退出，不让单次登记故障沿派发漏斗调用链上抛（对齐 ledger_has_pending
        # / run_backfill 的防护，code-review 1b907a3d581e / d18f3604a4ab）。
        # 本函数无 logger 入参，留痕走 todo.md；todo 写失败不再外抛，保持零动作。
        try:
            append_todo_line(
                project_root,
                f"回填登记 {archive_name} 失败（台账或 specs 目录读取异常），请人工检查后重试",
            )
        except OSError:
            pass
        return False
    changed = False
    adr_key = ADR_PREFIX + archive_name
    if adr_key not in ledger.entries:
        ledger.entries[adr_key] = ledger._new_entry(adr_key)
        changed = True
    for cap in caps:
        cap_key = CAPABILITY_PREFIX + cap
        if cap_key not in ledger.entries:
            ledger.entries[cap_key] = ledger._new_entry(cap_key)
            changed = True
        elif ledger.reset_pending(cap_key):
            changed = True
    if changed:
        ledger.save()
    return changed


# ── spawn（生产实现：claude -p 直跑主树） ────────────────────────────────


def _failure_attribution_tail(stdout: str, stderr: str, width: int = 400) -> str:
    """失败归因文本（reduce-cli-stderr-noise-attribution D3）。

    stderr 逐行过滤 CLI 启动期诊断噪声（``[claude-code:unrecognized_model]``
    每 run 恒 1 条，恰淹没真实死因尾 400 字符）后取尾部 width 字符；过滤后
    为空回退 stdout 尾部（``[claude-code:*]`` 诊断行只写 stderr，stdout 不过
    滤）；两者皆空返回空串，归因仅保留退出码前缀（与 runner._denoise_stderr
    「过滤后为空回退 Exit code」惯例一致）。``.out`` 留档不受影响——
    stdout/stderr 双留证，降噪只作用于归因消息。
    """
    from core.agent_runner.provider_circuit import (  # noqa: PLC0415
        is_cli_stderr_noise,
    )

    lines = [l for l in (stderr or "").splitlines() if not is_cli_stderr_noise(l)]
    if lines:
        return "\n".join(lines).strip()[-width:]
    return (stdout or "").strip()[-width:]


def _kill_process_group(proc: subprocess.Popen) -> None:
    """超时清场：killpg 整组收割 + 排干管道 + 强杀兜底。

    与 ``core.knowledge.DistillManager`` 的同故障形态对齐（本文件内同款实现，
    不改其对内私有的封装）：裸 ``subprocess.run``/``Popen.kill`` 超时只收直接
    子进程，claude 派生的孙进程未被收割，可存活继续写 ``spec/knowledge/``，
    与后续 validate/提交/回滚竞写。SIGKILL 后 ``communicate`` 仍可能永久阻塞
    ——孙进程若重新 setsid 逃出进程组并继承 stdout/stderr 管道，管道不关闭
    （core.knowledge code-review 44d833e20470 教训），此时强杀直接子进程并弃
    管道，保底让调用方 fail-open 路径继续走；弃管道后补一次限时 ``wait`` 尽力
    收割，避免常驻进程内每次超时清场残留一个僵尸子进程（code-review
    209d7134dc52）。
    """
    # 击杀经自保护守卫（add-killpg-self-guard，resolve 型）：守卫拒绝（自身组/
    # 非正 pgid）与组已不存在同样静默——MUST NOT 降级单 pid proc.kill
    # （pid=0 经 os.kill 折算同为调用者自身组广播）；既有 ESRCH 场景该降级
    # 本就 no-op（目标已亡），收口后行为不变。
    guard_killpg(
        proc.pid,
        signal.SIGKILL,
        caller="knowledge_backfill._kill_process_group",
        resolve=True,
    )
    try:
        proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
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
        # 尽力收割：强杀后不 wait 会残留僵尸子进程；孙进程仍持管道等收不回时
        # 放弃，交由 init 兜底回收
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass


def default_spawn(project_root: Path) -> SpawnFn:
    """生产 spawn：主树直跑 ``claude -p``（与前置 SPEC 蒸馏 run 同形态，
    真相源是 spec 元数据层，非产品代码，不走 worktree 实现车道）。"""

    def _spawn(prompt: str, run_id: str) -> str:
        # 收编进 harness.run_one_shot（add-harness-adapter-layer 4.1）：claude
        # 命令构造唯一入口在 claude_adapter.build_spawn_spec。与 core.knowledge
        # 蒸馏 spawn 同形态：无头 -p 必须显式提权，否则 LLM 写域映射/页面文件
        # 被权限拒绝、产物只能落 stdout（曾致 bootstrap-no-domain-map：25 分钟
        # 聚类成果随被丢弃的 stdout 蒸发）；提示词经 stdin 传入（argv 全文驻留
        # /proc/<pid>/cmdline 对同机其他用户可见，且单参数受 MAX_ARG_STRLEN
        # ≈128KB 约束——回填提示词内嵌各能力史前基线全文，超限即 spawn 以
        # E2BIG 失败且批次恒失败）；env 口径 ENV_MODE_CLEAN（agent-run 专用
        # 上下文键不进子进程环境，core.agent_env_keys 单一口径，对齐
        # core.knowledge._build_spawn_env：回填车道从 agent-run 会话内手工
        # 激活时 FENIX_RUN_* / CLAUDE_CODE_ENABLE_TODO_TOOLS 已在父环境，直传
        # 会令子 claude 误判自身运行上下文）；独立会话组（超时可 killpg 整组
        # 清场，裸 run 超时只杀直接子进程，孙进程可存活继续写真相源）。
        try:
            outcome = run_one_shot(
                ClaudeAdapter(),
                SpawnRequest(
                    prompt=prompt,
                    cwd=str(project_root),
                    # 现状形态无 --output-format（裸文本 stdout 留痕），显式
                    # None 压掉 SpawnRequest 的 stream-json 缺省
                    output_format=None,
                    permission_mode="bypassPermissions",
                    env_mode=ENV_MODE_CLEAN,
                    project_root=str(project_root),
                ),
                timeout=SPAWN_TIMEOUT_SECONDS,
                on_timeout=_kill_process_group,
            )
        except OneShotCommunicateError as e:
            # 通信期异常按既有语义透传原始异常类型（fail-open 调用方只看
            # 异常消息文本，类型保真不改变其 except Exception 口径）
            raise e.original from e.original
        if outcome.timed_out:
            raise RuntimeError(
                f"claude -p 回填 run {run_id} 超时（>{SPAWN_TIMEOUT_SECONDS}s），"
                "已终止进程组"
            )
        stdout, stderr = outcome.stdout, outcome.stderr
        # stdout/stderr 落盘留痕：run 失败可取证，不再依赖调用方是否消费返回值
        try:
            runs_dir = project_root / ".fenix" / "runs"
            runs_dir.mkdir(parents=True, exist_ok=True)
            (runs_dir / f"{run_id}.out").write_text(
                f"[returncode {outcome.returncode}]\n"
                f"[stdout]\n{stdout or ''}\n[stderr]\n{stderr or ''}\n",
                encoding="utf-8",
            )
        except OSError:
            pass
        if outcome.returncode != 0:
            tail = _failure_attribution_tail(stdout, stderr)
            msg = f"claude -p 回填 run {run_id} 退出码 {outcome.returncode}"
            if tail:
                msg = f"{msg}：{tail}"
            raise RuntimeError(msg)
        return stdout

    return _spawn


# ── 提示词拼装（core/knowledge_prompts/backfill.md 的动态段） ────────────


def _violations_block(violations: list[str]) -> str:
    if not violations:
        return ""
    return "## 上轮校验违规（本轮须全部修复，否则产出被放弃）\n\n" + "\n".join(
        f"- {v}" for v in violations
    ) + "\n"


# 公开别名（core.knowledge_audit 复用，避免 import 私有名）
violations_block = _violations_block
null_logger = _NullLogger
knowledge_dirty_files = _knowledge_dirty_files


def _now_local_parts() -> tuple:
    """当前本地时间与展示后缀（``("2026-09-30 10:33", "UTC+8")``）。

    真相源盖戳统一时间源（用户定调 2026-09-30：本地时区展示）。与
    ``core.knowledge.local_now_stamp`` 同逻辑——本模块被 knowledge.py 反向
    导入，独立实现避免循环依赖；时间产出统一走 timelib 原语（守卫棘轮）。
    """
    now = now_local()
    total_min = round((now.utcoffset() or timedelta(seconds=0)).total_seconds() / 60)
    sign = "+" if total_min >= 0 else "-"
    hours, minutes = divmod(abs(total_min), 60)
    tz = f"UTC{sign}{hours}" + (f":{minutes:02d}" if minutes else "")
    return now.strftime("%Y-%m-%d %H:%M"), tz


def build_prompt(
    mode: str,
    capabilities: Optional[list[str]] = None,
    batch: Optional[list[str]] = None,
    violations: Optional[list[str]] = None,
    chains: Optional[dict[str, list[str]]] = None,
    baselines: Optional[dict[str, str]] = None,
) -> str:
    """提示词 = backfill.md 契约 + 动态段占位填充（模式线 / 清单 / 违规反馈）。

    - ``bootstrap``：``capabilities`` = 链索引能力全集（聚类自举输入）；
    - ``batch``：``batch`` = 本批能力名；``chains`` = 能力 → 归档链；
      ``baselines`` = 能力 → 史前基线文本（链头输入，聚合成文时一并聚合）。
    """
    text = PROMPT_PATH.read_text(encoding="utf-8")
    if mode == "bootstrap":
        capabilities = capabilities or []
        text = text.replace(
            "{{MODE_LINE}}",
            "本次运行模式：**模式一（聚类自举）**——只执行「模式一：聚类自举」段，"
            "忽略模式二与模式三。",
        )
        text = text.replace("{{CAPABILITY_COUNT}}", str(len(capabilities)))
        text = text.replace(
            "{{CAPABILITY_LIST}}",
            "\n".join(f"- {name}" for name in capabilities) or "（空）",
        )
        text = text.replace("{{BATCH_SIZE}}", "0")
        text = text.replace("{{BATCH_LIST}}", "（本次不适用）")
    elif mode == "batch":
        batch = batch or []
        chains = chains or {}
        baselines = baselines or {}
        text = text.replace(
            "{{MODE_LINE}}",
            "本次运行模式：**模式二（能力聚合蒸馏批次）**——只执行「模式二：能力"
            "聚合蒸馏批次」段，忽略模式一与模式三。",
        )
        text = text.replace("{{CAPABILITY_COUNT}}", "0")
        text = text.replace("{{CAPABILITY_LIST}}", "（本次不适用）")
        text = text.replace("{{BATCH_SIZE}}", str(len(batch)))
        text = text.replace("{{BATCH_LIST}}", _batch_list_block(batch, chains, baselines))
    elif mode == "adr":
        batch = batch or []
        text = text.replace(
            "{{MODE_LINE}}",
            "本次运行模式：**模式三（ADR 抽取批次）**——只执行「模式三：ADR 抽取"
            "批次」段，忽略模式一与模式二。",
        )
        text = text.replace("{{CAPABILITY_COUNT}}", "0")
        text = text.replace("{{CAPABILITY_LIST}}", "（本次不适用）")
        text = text.replace("{{BATCH_SIZE}}", str(len(batch)))
        text = text.replace(
            "{{BATCH_LIST}}",
            "\n".join(f"- {name}" for name in batch) or "（空）",
        )
    else:  # pragma: no cover - 调用方约束
        raise ValueError(f"unknown backfill prompt mode: {mode}")
    text = text.replace(
        "{{DOMAIN_MAP_PATH}}", DOMAIN_MAP_RELPATH
    ).replace("{{VIOLATIONS_BLOCK}}", _violations_block(violations or []))
    # [fenix-ignore:8980a66d334c] 条目描述的两次独立调用 _now_local_parts 在当前代码中不存在：已取一次解包为 now_local/now_tz 复用（见下注）
    now_local, now_tz = _now_local_parts()
    # 同一份提示词内时间与时区标注取自同一次时钟读数：分两次取值跨分钟/
    # DST 切换边界时两段会不一致（code-review 8980a66d334c）。
    return text.replace("{{NOW_LOCAL}}", now_local).replace("{{NOW_TZ}}", now_tz)


def _batch_list_block(
    batch: list[str],
    chains: dict[str, list[str]],
    baselines: dict[str, str],
) -> str:
    """批次清单块：逐能力标注完整链（日期升序）与史前基线（链头输入）。"""
    lines: list[str] = []
    for cap in batch:
        chain = chains.get(cap) or []
        line = f"- {cap}（链 {len(chain)} 份 delta：{' → '.join(chain) if chain else '无'}）"
        baseline = baselines.get(cap)
        if baseline:
            line += f"\n  - 史前基线（链头输入）：{baseline}"
        lines.append(line)
    return "\n".join(lines) or "（空）"


# ── 史前复原 run 提示词（core/knowledge_prompts/prehistoric.md） ─────────


def first_commit_ref(project_root: Path) -> str:
    """仓库首提交短 ref（史前窗口起点；非 git / 失败回退空串占位）。"""
    try:
        out = _git(Path(project_root), "rev-list", "--max-parents=0", "HEAD")
    except Exception:  # noqa: BLE001 - 非 git 目录/超时按占位降级
        return ""
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines[0][:9] if lines else ""


def build_prehistoric_prompt(
    project_root: Path,
    covered_caps,
    violations: Optional[list[str]] = None,
) -> str:
    """史前复原提示词 = prehistoric.md 契约 + 动态段（窗口锚点 / 求差基准）。"""
    text = PREHISTORIC_PROMPT_PATH.read_text(encoding="utf-8")
    text = text.replace("{{UNTIL_DATE}}", PREHISTORIC_UNTIL)
    text = text.replace("{{FIRST_REF}}", first_commit_ref(project_root) or "<首提交ref>")
    text = text.replace("{{PREHISTORIC_JSON_PATH}}", PREHISTORIC_JSON_RELPATH)
    text = text.replace(
        "{{COVERED_CAPS}}",
        "\n".join(f"- {c}" for c in sorted(covered_caps)) or "（空）",
    )
    now_local, now_tz = _now_local_parts()
    return (
        text.replace("{{VIOLATIONS_BLOCK}}", _violations_block(violations or []))
        .replace("{{NOW_LOCAL}}", now_local)
        .replace("{{NOW_TZ}}", now_tz)
    )


# ── 链索引、批次划分与规模统计 ───────────────────────────────────────────


def build_chain_index(project_root: Path) -> dict[str, list[str]]:
    """能力聚合链索引（方案 B 核心，纯机械零 LLM）：遍历 ``spec/archive/*/specs/``
    目录名（能力名）× 归档目录名排序，产出 ``能力 → 触碰它的全部归档 delta 链``。

    归档目录名以 ``YYYY-MM-DD`` 日期前缀开头，字典序即日期升序——链序天然按
    时间排列，聚合蒸馏按链序一次成文最终态页面。无 ``specs/`` 的归档不触碰
    任何能力（只可能进 ADR 抽取维度）。
    """
    archive_dir = Path(project_root) / "spec" / "archive"
    index: dict[str, list[str]] = {}
    if not archive_dir.is_dir():
        return index
    for archive in sorted(p.name for p in archive_dir.iterdir() if p.is_dir()):
        specs = archive_dir / archive / "specs"
        if not specs.is_dir():
            continue
        for cap in sorted(p.name for p in specs.iterdir() if p.is_dir()):
            index.setdefault(cap, []).append(archive)
    return index


def build_batches(
    domain_map: dict[str, str], names: list[str]
) -> list[list[str]]:
    """按域分组、批 ≤20（同域一个批次流，域内超顶再切片；无域归位条目入
    ``_unassigned`` 兜底域）。确定性：域与成员均按名排序。

    v2（方案 B）：``names`` 是**能力名**（链索引键集），``domain_map`` 由聚类
    自举产出 ``能力名 → 域``——批次从归档粒度改为能力粒度，页间独立，批序
    与正确性解耦（可并行、断点按能力续跑）。
    """
    by_domain: dict[str, list[str]] = {}
    for name in sorted(names):
        domain = domain_map.get(name) or "_unassigned"
        by_domain.setdefault(domain, []).append(name)
    batches: list[list[str]] = []
    for domain in sorted(by_domain):
        members = by_domain[domain]
        for i in range(0, len(members), BATCH_SIZE_MAX):
            batches.append(members[i : i + BATCH_SIZE_MAX])
    return batches


def scale_stats(project_root: Path, log=None) -> dict[str, int]:
    """真相源规模统计：域数 / 能力页数 / ADR 数 / 总行数（汇报与膨胀趋势共用）。

    单个知识页不可读（权限/EIO）时 fail-open 计 0 行并 WARNING 留痕，不以未
    处理异常掀翻调用方车道（对齐本文件其余文件读取的防护口径，
    code-review 4fea0d88eed2）；``log`` 缺省静默替身（外部调用方传参可选）。
    """
    log = log or _NullLogger()
    kdir = Path(project_root) / KNOWLEDGE_DIR
    domains_dir = kdir / "domains"
    adr_dir = kdir / "adr"
    domains = (
        len([p for p in domains_dir.iterdir() if (p / "_domain.md").is_file()])
        if domains_dir.is_dir()
        else 0
    )
    pages = 0
    lines = 0
    if domains_dir.is_dir():
        for page in domains_dir.rglob("*.md"):
            if page.name == "_domain.md":
                continue
            pages += 1
            try:
                text = page.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                log.warning(
                    "knowledge",
                    f"回填规模统计：知识页 {page.name} 读取失败（计 0 行跳过）：{e}",
                )
                continue
            lines += len(text.splitlines())
    for nav in (kdir / "index.md",):
        if nav.is_file():
            try:
                text = nav.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                log.warning(
                    "knowledge",
                    f"回填规模统计：index.md 读取失败（计 0 行跳过）：{e}",
                )
                continue
            lines += len(text.splitlines())
    adrs = (
        len([p for p in adr_dir.glob("ADR-*.md") if p.is_file()])
        if adr_dir.is_dir()
        else 0
    )
    return {"domains": domains, "pages": pages, "adrs": adrs, "lines": lines}


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ── 史前求差与自举清理（任务 2.3） ───────────────────────────────────────


def _valid_domain_component(v: object) -> bool:
    """LLM 产出的域名合法单路径成分判定：字符串、非空、不含路径分隔符、
    不为点号目录。``_prune_stale_domains`` 的白名单与
    ``_missing_prehistoric_pages`` 的路径拼接共用——畸形值（带斜杠/相对
    引用）不得参与路径语义（code-review 9bd4d8ede459）。
    """
    return (
        isinstance(v, str)
        and bool(v)
        and "/" not in v
        and v not in (".", "..")
    )


def _missing_prehistoric_pages(
    project_root: Path, inventory: list, chain_index: dict
) -> list[str]:
    """求差核验：清单中未被归档覆盖的能力必须有史前页落盘（入正确域）。

    Returns:
        缺页能力清单（空列表 = 通过）。
    """
    missing: list[str] = []
    for item in inventory:
        if not isinstance(item, dict):
            continue
        cap = item.get("capability")
        if not _valid_domain_component(cap):
            # LLM 清单产出的 capability 非法（缺失/非字符串/含路径分隔符/点号
            # 目录）：非 hashable 类型 `cap in chain_index` 直接抛 TypeError，
            # 本函数在 run_backfill 史前复原段的裸 try 之外调用，异常会掀翻
            # 整条回填车道；畸形成分拼出的 page 路径会越出 domains 目录、
            # is_file 探测到真相源之外的路径，把能力误判已覆盖跳过补写。同
            # domain 侧纪律：不拿畸形值做覆盖判定，按缺页登记提示人工
            # （code-review 80a84d1821ac）。
            missing.append(
                f"{cap}（域 {str(item.get('domain') or '').strip() or '未声明'}）"
            )
            continue
        # [fenix-ignore:80a84d1821ac] 条目描述的未校验 capability 直接 `cap in chain_index` 在当前代码中不存在：上方已先以 _valid_domain_component 校验类型与路径成分，畸形值按缺页登记交人工
        if cap in chain_index:
            continue  # 已被归档覆盖：不写史前页（baseline 走链头输入）
        domain = str(item.get("domain") or "").strip()
        if not _valid_domain_component(domain):
            # LLM 清单产出的 domain 非法（空/含斜杠/点号目录）：拼出的 page
            # 路径会越出 domains 目录、is_file 探测到真相源之外的路径，缺页
            # 核验失真（误判已覆盖跳过补写，或对合法能力恒报缺页）。不拿畸形
            # 路径做覆盖判定，直接按缺页登记提示人工（不静默忽略）。
            missing.append(f"{cap}（域 {domain or '未声明'}）")
            continue
        page = project_root / KNOWLEDGE_DIR / "domains" / domain / f"{cap}.md"
        if not page.is_file():
            missing.append(f"{cap}（域 {domain or '未声明'}）")
    return missing


def _clean_untracked_knowledge(project_root: Path, log) -> None:
    """自举重跑清场：清 ``spec/knowledge/`` 下未跟踪残留。

    e2e fixture 遗留（zn 演示域、fixture ADR、graph/ 产物）均为未跟踪文件；
    只动未跟踪内容（git clean），已入库内容不受影响——避免真实抽取的 ADR
    编号与 fixture 条目重复触发校验失败。

    ``-fd`` 会无差别删除目录下一切未跟踪文件与目录（含用户手工新建、尚未提交
    的知识页草稿），且未跟踪内容无版本兜底、删后只能靠文件系统工具找回——
    删除前先 ``-nd`` 干跑取删除清单留痕告警（code-review bb5ea5f1ea0d）。
    git 缺失/超时不沿自举段上抛掀翻车道，WARNING 留痕后返回（code-review
    b35ae9ddcaaf）——自举清场属尽力而为，不应阻塞回填。
    """
    try:
        dry = subprocess.run(
            ["git", "clean", "-nd", "--", KNOWLEDGE_DIR],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            # encoding/errors 固化（对齐 _git / _knowledge_dirty_files）：裸
            # text=True 走 locale strict 解码，删除清单含非 UTF-8 文件名字节
            # 时抛 UnicodeDecodeError（ValueError），穿透 except 口径掀翻自举
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        # 干跑失败时删除清单不可知，跳过实际清理（避免无枚举兜底的破坏性删除）
        log.warning(
            "knowledge",
            f"回填自举清理干跑不可用（fail-open），跳过未跟踪残留清场，"
            f"请人工核查：{str(exc)[:200]}",
        )
        return
    if dry.returncode == 0 and dry.stdout.strip():
        log.warning(
            "knowledge",
            "回填自举清理将删除 spec/knowledge/ 下未跟踪内容（不可从 git 找回，"
            "如含手工草稿请先移出）：" + dry.stdout.strip()[:500],
        )
    try:
        proc = subprocess.run(
            ["git", "clean", "-qfd", "--", KNOWLEDGE_DIR],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            # 同上：固化 UTF-8 解码（stderr 留痕消费同受解码异常威胁）
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        log.warning(
            "knowledge",
            "回填自举清理未跟踪残留失败（fail-open）：git 不可用或超时，"
            "spec/knowledge/ 下未跟踪残留未清，请人工核查",
        )
        return
    if proc.returncode != 0:  # noqa: BLE001 - fail-open 清理不阻塞自举
        log.warning(
            "knowledge",
            f"回填自举清理未跟踪残留失败（fail-open）：{proc.stderr.strip()[:200]}",
        )


def _domain_has_tracked_content(project_root: Path, domain_dir: Path) -> bool:
    """域目录内是否存在 git 已跟踪（已入库）文件。git 不可用/超时按 False
    降级——剪枝照常执行，删除前留痕已足够人工从 git 找回。"""
    try:
        proc = subprocess.run(
            [
                "git",
                "ls-files",
                "--",
                domain_dir.relative_to(project_root).as_posix(),
            ],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            # encoding/errors 固化（对齐 _git / _knowledge_dirty_files）：
            # ls-files stdout 含非 UTF-8 文件名字节时 strict 解码抛
            # UnicodeDecodeError，穿透 except 口径掀翻域剪枝
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if proc.returncode != 0:
        return False
    return bool(proc.stdout.strip())


def _prune_stale_domains(project_root: Path, domain_map: dict, log) -> list[str]:
    """以真实聚类重建域清单：不在新域集合中的既有域目录整体移除（fixture
    遗留域，如 zn-demo-domain）。含 git 已跟踪内容的域同样按白名单移除，但
    单独告警留痕——单次 LLM 域命名漂移不应静默连带删除已入库知识页，误删
    可从 git 恢复（code-review 6736a158bcf4）。Returns: 被移除的域名清单。"""
    domains_dir = project_root / KNOWLEDGE_DIR / "domains"
    removed: list[str] = []
    removed_tracked: list[str] = []
    if not domains_dir.is_dir():
        return removed
    # LLM 值不信任：只收合法单路径成分，畸形值（带路径分隔符/相对引用）不得
    # 影响白名单判定
    keep = {v for v in domain_map.values() if _valid_domain_component(v)}
    for d in sorted(domains_dir.iterdir()):
        if d.is_dir() and d.name not in keep:
            if _domain_has_tracked_content(project_root, d):
                removed_tracked.append(d.name)
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d.name)
    if removed:
        log.warning(
            "knowledge", f"回填自举重建域清单，移除遗留域：{', '.join(removed)}"
        )
    if removed_tracked:
        log.warning(
            "knowledge",
            "回填自举重建域清单：被移除域含 git 已跟踪（已入库）内容，如系 "
            "LLM 域命名漂移误删请从 git 恢复：" + ", ".join(removed_tracked),
        )
    return removed


# ── 跨进程单写者锁（与 core.knowledge.DistillManager 同一把锁） ──────────


@contextmanager
def knowledge_distill_lock(project_root: Path):
    """回填写段互斥：与 ``DistillManager._acquire_file_lock`` 同一
    ``.fenix/knowledge-distill.lock`` flock（阻塞等待）。

    回填车道（手工激活）与蒸馏车道（daemon 挂载）分属不同进程，此前互斥
    只靠派发漏斗 ``ledger_has_pending`` 的快照判定，回填刚激活台账尚未落盘
    首个 pending、或蒸馏 run 已在飞时激活回填，两进程会同时写
    ``spec/knowledge/``，随后任意一方 restore/clean/discard 即清掉对方未提交
    产出（code-review 2443e98dc1f0）。写段取同一把锁把「单写者」从约定
    升级为机制。

    MUST NOT 在已持该锁的进程内嵌套再取（flock 对同进程的第二个 fd 同样
    互斥，会自阻塞）：本车道写段内不经 DistillManager 任何加锁路径。
    """
    import fcntl

    lock_dir = Path(project_root) / ".fenix"
    lock_dir.mkdir(parents=True, exist_ok=True)
    fh = open(lock_dir / "knowledge-distill.lock", "w")  # noqa: SIM115 — 生命周期=with
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


# ── 车道主入口 ───────────────────────────────────────────────────────────


def run_backfill(
    project_root,
    config: Optional[dict] = None,
    logger=None,
    spawn: Optional[SpawnFn] = None,
) -> dict:
    """回填车道入口：自举 → 分批 → 校验提交 → 收敛汇报。可中断重入。

    spawn 可注入替身（run 内单测）；config 预留（车道为手工激活，不挂配置开关）。
    返回 dict：triggered / reason / batches_* / failed / scale / converged。
    """
    project_root = Path(project_root)
    log = logger or _NullLogger()
    core = load_knowledge_core()
    if core is None:
        log.warning(
            "knowledge",
            "回填车道跳过：core.knowledge 不可用（前置 SPEC add-knowledge-atlas 未合并），"
            "本车道零动作",
        )
        return {"triggered": False, "reason": "knowledge-core-unavailable"}
    validate = core.validate_knowledge
    commit = resolve_commit(core)
    spawn = spawn or default_spawn(project_root)

    archive_dir = project_root / "spec" / "archive"
    archives = (
        sorted(p.name for p in archive_dir.iterdir() if p.is_dir())
        if archive_dir.is_dir()
        else []
    )
    if not archives:
        return {"triggered": False, "reason": "no-archives"}

    # 提示词模板入口预读一次（code-review c07182378afd）：build_prompt /
    # build_prehistoric_prompt 的模板 read_text 落在各段 run 的 try 之外，
    # 模板缺失/不可读会以裸异常掀翻车道，与「单段失败不阻塞车道」口径相悖。
    # 入口预读把确定性故障提前为显式登记 todo 待人工、零动作退出（对齐台账
    # 不可读的 fail-open 先例）；不吞错——读不到模板即终止本车道，绝不以空
    # 提示词派发 run。
    try:
        for _tpl in (PROMPT_PATH, PREHISTORIC_PROMPT_PATH):
            _tpl.read_text(encoding="utf-8")
    except OSError as e:
        log.warning(
            "knowledge", f"回填提示词模板读取失败，本车道跳过待人工检查：{e}"
        )
        _append_todo_fail_open(
            project_root,
            "回填提示词模板读取失败，请检查 core/knowledge_prompts/ 后重跑回填",
            log,
        )
        return {"triggered": False, "reason": "prompt-template-unreadable"}

    chain_index = build_chain_index(project_root)
    try:
        ledger = BackfillLedger.load(project_root / LEDGER_RELPATH)
    except (OSError, ValueError):
        # 台账在盘但不可读时 fail-open 零动作退出，不以未处理异常掀翻车道
        # （对齐 ledger_has_pending 的防护，code-review 1b907a3d581e）
        log.warning(
            "knowledge", f"回填台账 {LEDGER_RELPATH} 读取失败，本车道跳过待人工检查"
        )
        _append_todo_fail_open(
            project_root,
            f"回填台账 {LEDGER_RELPATH} 读取失败，请人工检查后重跑回填",
            log,
        )
        return {"triggered": False, "reason": "ledger-unreadable"}
    if ledger.legacy_keys:
        log.warning(
            "knowledge",
            f"回填台账含 {len(ledger.legacy_keys)} 条 v1 旧格式条目，已作废剔除"
            f"（v2 条目保留）：{', '.join(ledger.legacy_keys[:5])}",
        )
    ledger.reconcile(chain_index, archives)
    # 台账落盘失败不掀翻车道（fail-open，对齐批次循环同款防护）：.fenix 只读/
    # 磁盘满等 OSError 不让本车道以未处理异常告终，留痕后继续——后续批次 save
    # 持锁重读盘上全量条目重写可自愈
    try:
        ledger.save()
    except OSError as e:
        log.warning("knowledge", f"回填台账落盘失败（fail-open）：{e}")
    todo_caps = ledger.pending_capabilities()
    todo_adr = ledger.pending_adr_archives()

    # 收敛幂等：台账非空且两维度全部终态 → 零派发只汇报
    if ledger.entries and not todo_caps and not todo_adr:
        counts = ledger.counts()
        return {
            "triggered": False,
            "reason": "converged",
            "converged": True,
            "counts": counts,
            "scale": scale_stats(project_root, log=log),
        }

    domain_map_path = project_root / DOMAIN_MAP_RELPATH
    domain_map = _read_json(domain_map_path)
    if not isinstance(domain_map, dict) or not domain_map:
        # ── 聚类自举 run（v2：聚类对象从归档名改为链索引能力名）──
        # 写段取蒸馏锁：与 DistillManager 串行，防两车道并发写 spec/knowledge/
        with knowledge_distill_lock(project_root):
            # 本段 run 前的脏文件基线（失败时差集回滚只清本车道触达文件）
            dirty_baseline = _knowledge_dirty_files(project_root)
            # 自举重跑清场：fixture 遗留（未跟踪）先清，跑完再按真实聚类删遗留域
            _clean_untracked_knowledge(project_root, log)
            # 本段 run 前的违规基线：提交闸门只否决本轮新引入的违规，真相源既有
            # 无关违规不拦提交（差集口径对齐 knowledge_audit，code-review
            # 84727f16ab35）
            before_violations = {str(v) for v in (validate(project_root) or [])}
            chain_caps = sorted(chain_index)
            prompt = build_prompt("bootstrap", capabilities=chain_caps)
            run_id = f"kb-bootstrap-{int(time.time())}"
            try:
                spawn(prompt, run_id)
            except Exception as e:  # noqa: BLE001 - fail-open 记台账不中断
                _append_todo_fail_open(
                    project_root,
                    f"回填聚类自举 run 失败（{run_id}）：{e}",
                    log,
                )
                return {"triggered": True, "ok": False, "reason": "bootstrap-spawn-failed"}
            domain_map = _read_json(domain_map_path)
            if not isinstance(domain_map, dict) or not domain_map:
                _append_todo_fail_open(
                    project_root,
                    f"回填聚类自举 run（{run_id}）未产出域归位清单 {DOMAIN_MAP_RELPATH}，"
                    "请人工检查后重跑回填",
                    log,
                )
                return {"triggered": True, "ok": False, "reason": "bootstrap-no-domain-map"}
            base_prompt = build_prompt("bootstrap", capabilities=chain_caps)
            try:
                ok, violations = _validate_with_repair(
                    project_root, validate, spawn, base_prompt, run_id,
                    before_violations=before_violations,
                )
            except Exception as e:  # noqa: BLE001 - 单段失败不阻塞车道，可重入
                _append_todo_fail_open(
                    project_root,
                    f"回填自举校验/修正 run 失败（{run_id}）：{e}",
                    log,
                )
                return {
                    "triggered": True,
                    "ok": False,
                    "reason": "bootstrap-validate-failed",
                }
            if not ok:
                discard_knowledge_changes(project_root, before=dirty_baseline, log=log)
                _append_todo_fail_open(
                    project_root,
                    "回填自举产出校验 "
                    f"{MAX_FIX_ROUNDS} 轮后仍失败，已放弃本次产出：{violations[:3]}",
                    log,
                )
                return {
                    "triggered": True,
                    "ok": False,
                    "reason": "bootstrap-invalid",
                    "violations": violations[:10],
                }
            # 剪枝移到校验通过之后：白名单出自 LLM 域清单，先删后验会在清单
            # 缺漏/畸形时把既有真实域内容物理删除并随提交落库；校验失败路径
            # 此时还未删，无需依赖 restore 兜底（code-review 99e9e002cba5）。
            # 但剪枝仍发生在校验与提交之间——删域造成的 index/跨页链接断裂
            # 须在提交前再拦一次，不随坏状态落库（code-review 6736a158bcf4）
            _prune_stale_domains(project_root, domain_map, log)
            # 剪枝闸门同差集口径：只否决剪枝新引入的违规（域删除导致的
            # index/跨页链接断裂），既有无关违规不拦提交
            prune_violations = [
                str(v)
                for v in (validate(project_root) or [])
                if str(v) not in before_violations
            ]
            if prune_violations:
                discard_knowledge_changes(project_root, before=dirty_baseline, log=log)
                _append_todo_fail_open(
                    project_root,
                    "回填自举剪枝后校验失败，已放弃本次产出待人工检查重跑："
                    f"{prune_violations[:3]}",
                    log,
                )
                return {
                    "triggered": True,
                    "ok": False,
                    "reason": "bootstrap-prune-invalid",
                    "violations": prune_violations[:10],
                }
            try:
                commit(project_root, [KNOWLEDGE_DIR], "[fenix] knowledge: backfill bootstrap")
            except Exception as e:  # noqa: BLE001 - 单段失败不阻塞车道，可重入
                _append_todo_fail_open(
                    project_root, f"回填自举提交失败（{run_id}）：{e}", log
                )
                return {
                    "triggered": True,
                    "ok": False,
                    "reason": "bootstrap-commit-failed",
                }

    # ── 史前复原段（prehistoric bootstrap：git 考古 → 求差 → 史前页/链头）──
    prehistoric_path = project_root / PREHISTORIC_JSON_RELPATH
    inventory = _read_json(prehistoric_path)
    if isinstance(inventory, list) and inventory:
        # 重入复用磁盘旧清单前先对覆盖集求差：回填是长跑车道，期间新归档经
        # register_archive_pending 重置能力为 pending 后重入，新触碰的能力不在
        # 旧清单里——链头缺史前基线会让聚合页静默缺失史前窗口内容。存在旧
        # 清单未覆盖的 pending 能力时整段重跑史前复原（code-review 387b3f802be7）
        inv_caps = {
            str(item.get("capability"))
            for item in inventory
            if isinstance(item, dict) and item.get("capability")
        }
        if any(cap not in inv_caps for cap in todo_caps):
            inventory = None
        else:
            # 覆盖差集通过还不够：prehistoric-missing-pages 早退登记的 todo 指
            # 引「人工检查后重跑回填」自愈，但缺页能力来自旧清单本身（求差核验
            # 的入参），必在 inv_caps，且按构造不在 chain_index（核验对归档覆盖
            # 能力直接 continue）——故上方差集条件对缺页能力恒 False，缺页时旧
            # 清单仍被复用、史前段整体跳过，单纯重跑既不补页也不再报错。复用前
            # 对磁盘旧清单再做一次缺页核验，非空即置空强制重跑史前段，与 todo
            # 指引的自愈路径对齐（code-review e0701d24cf1b）。核验只逐条 is_file
            # 探测、无考古/LLM 开销；异常 fail-closed 按需重跑处理——宁可多花
            # 一次史前 run，不带病复用旧清单，也不让核验异常掀翻重入路径。
            try:
                stale_missing = _missing_prehistoric_pages(
                    project_root, inventory, chain_index
                )
            except Exception:  # noqa: BLE001 - 核验异常 fail-closed，不外抛
                log.warning(
                    "knowledge",
                    "重入复用史前清单缺页核验异常，按需重跑史前复原段处理",
                )
                inventory = None
            else:
                if stale_missing:
                    log.warning(
                        "knowledge",
                        "重入检测到旧史前清单缺页（"
                        f"{', '.join(stale_missing[:5])}），重跑史前复原段补齐",
                    )
                    inventory = None
    if not isinstance(inventory, list) or not inventory:
        # 写段取蒸馏锁（同聚类自举段）
        with knowledge_distill_lock(project_root):
            # 本段 run 前的脏文件基线（失败时差集回滚只清本车道触达文件）
            dirty_baseline = _knowledge_dirty_files(project_root)
            # 本段 run 前的违规基线：提交闸门只否决本轮新引入的违规（同自举段）
            before_violations = {str(v) for v in (validate(project_root) or [])}
            prompt = build_prehistoric_prompt(project_root, chain_index)
            run_id = f"kb-prehistoric-{int(time.time())}"
            try:
                spawn(prompt, run_id)
            except Exception as e:  # noqa: BLE001 - fail-open 记台账不中断
                _append_todo_fail_open(
                    project_root, f"回填史前复原 run 失败（{run_id}）：{e}", log
                )
                return {"triggered": True, "ok": False, "reason": "prehistoric-spawn-failed"}
            inventory = _read_json(prehistoric_path)
            if not isinstance(inventory, list) or not inventory:
                _append_todo_fail_open(
                    project_root,
                    f"回填史前复原 run（{run_id}）未产出史前清单 "
                    f"{PREHISTORIC_JSON_RELPATH}，请人工检查后重跑回填",
                    log,
                )
                return {"triggered": True, "ok": False, "reason": "prehistoric-no-inventory"}
            missing = _missing_prehistoric_pages(project_root, inventory, chain_index)
            if missing:
                _append_todo_fail_open(
                    project_root,
                    f"回填史前复原 run（{run_id}）未覆盖能力缺史前页："
                    f"{', '.join(missing[:5])}，请人工检查后重跑回填",
                    log,
                )
                return {"triggered": True, "ok": False, "reason": "prehistoric-missing-pages"}
            base_prompt = build_prehistoric_prompt(project_root, chain_index)
            try:
                ok, violations = _validate_with_repair(
                    project_root, validate, spawn, base_prompt, run_id,
                    before_violations=before_violations,
                )
            except Exception as e:  # noqa: BLE001 - 单段失败不阻塞车道，可重入
                _append_todo_fail_open(
                    project_root,
                    f"回填史前复原校验/修正 run 失败（{run_id}）：{e}",
                    log,
                )
                return {
                    "triggered": True,
                    "ok": False,
                    "reason": "prehistoric-validate-failed",
                }
            if not ok:
                discard_knowledge_changes(project_root, before=dirty_baseline, log=log)
                _append_todo_fail_open(
                    project_root,
                    "回填史前复原产出校验 "
                    f"{MAX_FIX_ROUNDS} 轮后仍失败，已放弃本次产出：{violations[:3]}",
                    log,
                )
                return {
                    "triggered": True,
                    "ok": False,
                    "reason": "prehistoric-invalid",
                    "violations": violations[:10],
                }
            try:
                commit(project_root, [KNOWLEDGE_DIR], "[fenix] knowledge: backfill prehistoric")
            except Exception as e:  # noqa: BLE001 - 单段失败不阻塞车道，可重入
                _append_todo_fail_open(
                    project_root, f"回填史前复原提交失败（{run_id}）：{e}", log
                )
                return {
                    "triggered": True,
                    "ok": False,
                    "reason": "prehistoric-commit-failed",
                }

    # 求差：已被归档覆盖的能力，其史前基线作为链头输入聚合蒸馏单元
    baselines: dict[str, str] = {}
    for item in inventory if isinstance(inventory, list) else []:
        if not isinstance(item, dict):
            continue
        cap, baseline = item.get("capability"), item.get("baseline")
        if cap and baseline and cap in chain_index:
            baselines[str(cap)] = str(baseline)

    # ── 能力聚合批次（方案 B：蒸馏单元 = 能力，页间独立、批序无关）──
    batches = build_batches(domain_map, todo_caps)
    total = len(batches)
    ok_batches: list[int] = []
    failed_batches: list[dict] = []
    # 提交失败但内容有效、尚未落库的台账键（fail-open 遗留）：任一批次提交
    # 成功即被 pathspec 扫入落库并清空；遇到回滚/收尾仍未落库则打回 pending，
    # 保证台账不虚报已完成（code-review 3fd930cb6bbd）。
    uncommitted_keys: set[str] = set()
    for i, batch in enumerate(batches, 1):
        # 写段取蒸馏锁：spawn→校验→提交/回滚作为整体与 DistillManager 串行，
        # 防两车道并发写 spec/knowledge/（code-review 2443e98dc1f0）
        with knowledge_distill_lock(project_root):
            # 本批 run 前的脏文件基线（失败时差集回滚只清本车道触达文件）
            dirty_baseline = _knowledge_dirty_files(project_root)
            # 本批 run 前的违规基线：提交闸门只否决本轮新引入的违规，真相源既有
            # 无关违规不拦提交（差集口径对齐 knowledge_audit，code-review
            # 84727f16ab35）
            before_violations = {str(v) for v in (validate(project_root) or [])}
            base_prompt = build_prompt(
                "batch",
                batch=batch,
                chains={c: chain_index.get(c, []) for c in batch},
                baselines=baselines,
            )
            run_id = f"kb-batch{i}-{int(time.time())}"
            try:
                spawn(base_prompt, run_id)
                ok, violations = _validate_with_repair(
                    project_root, validate, spawn, base_prompt, run_id,
                    before_violations=before_violations,
                )
            except Exception as e:  # noqa: BLE001 - 单批失败不阻塞后续批
                ok, violations = False, [f"run 派发/执行失败：{e}"]
            if ok:
                # 校验通过即落库；提交失败 fail-open 记日志（内容已在盘上，
                # 后续批次的 pathspec 提交会自然扫入）
                try:
                    commit(
                        project_root,
                        [KNOWLEDGE_DIR],
                        f"[fenix] knowledge: backfill batch {i}/{total}",
                    )
                except Exception as e:  # noqa: BLE001
                    log.warning("knowledge", f"回填批次 {i}/{total} 提交失败（fail-open）：{e}")
                    uncommitted_keys.update(CAPABILITY_PREFIX + cap for cap in batch)
                else:
                    uncommitted_keys.clear()
                # 回填在飞期间新登记的归档（register_archive_pending 在派发
                # 漏斗进程并发改盘台账）可能触碰本批能力：车道入口一次性构建
                # 的 chain_index 不含其 delta，此处若照常标 distilled，台账按
                # 条合并以 updated_at 较新者胜、会覆盖登记进程的 pending 写入，
                # 下轮重入收敛判定即跳过该能力，新归档的溯源行对该能力页永久
                # 缺失。重扫链索引与提示词所用链比对，链有增变的条目保持
                # pending，下轮重入按新链重新聚合（code-review c06e4666a93b）。
                fresh_index = build_chain_index(project_root)
                for cap in batch:
                    cap_key = CAPABILITY_PREFIX + cap
                    if fresh_index.get(cap, []) != chain_index.get(cap, []):
                        ledger.reset_pending(cap_key)
                        log.warning(
                            "knowledge",
                            f"回填批次 {i}/{total}：能力 {cap} 在聚合期间有新登记"
                            "归档触碰（本轮链未含其 delta），保持 pending 待重入"
                            "按新链重新聚合",
                        )
                        continue
                    ledger.mark(cap_key, STATUS_DISTILLED, batch=i)
                ok_batches.append(i)
            else:
                # 差集回滚只清本批新增脏路径：前批提交失败仍在盘上的产出落在
                # 基线内会被保留并告警（不连带清除），但内容尚未落库——台账打回
                # pending 待重入对账重做，不让台账宣称未落库内容已完成
                stale = sorted(uncommitted_keys)
                for key in stale:
                    ledger.reset_pending(key)
                if stale:
                    _append_todo_fail_open(
                        project_root,
                        f"回填批次 {i}/{total} 回滚保留在盘产出（差集回滚只清本批"
                        f"新增脏路径），此前提交失败批次产出未落库，相关条目"
                        f"已打回 pending 待重入对账重做："
                        f"{', '.join(k.split(':', 1)[1] for k in stale[:5])}",
                        log,
                    )
                uncommitted_keys.clear()
                discard_knowledge_changes(project_root, before=dirty_baseline, log=log)
                for cap in batch:
                    ledger.mark(CAPABILITY_PREFIX + cap, STATUS_FAILED, batch=i)
                _append_todo_fail_open(
                    project_root,
                    f"回填批次 {i}/{total} 校验 {MAX_FIX_ROUNDS} 轮后仍失败（"
                    f"{len(batch)} 个能力），已回滚半成品：{violations[:3]}",
                    log,
                )
                failed_batches.append(
                    {"batch": i, "capabilities": batch, "violations": violations[:5]}
                )
                log.warning(
                    "knowledge",
                    f"回填批次 {i}/{total} 失败（{len(batch)} 能力），继续后续批次",
                )
        # 台账落盘失败不掀翻车道（fail-open，对齐入口台账读防护 1b907a3d581e）：
        # .fenix 只读/磁盘满等 OSError 不让已跑完的批次沿调用链变成未捕获异常，
        # 本批留痕后继续后续批，下一批 save 持锁重读盘上全量条目重写可自愈
        try:
            ledger.save()
        except OSError as e:
            log.warning(
                "knowledge", f"回填批次 {i}/{total} 台账落盘失败（fail-open）：{e}"
            )

    # ── ADR 抽取批次（模式三：design.md 决策扫描，归档粒度）──
    no_design = [
        a for a in todo_adr
        if not (project_root / "spec" / "archive" / a / "design.md").is_file()
    ]
    with_design = [a for a in todo_adr if a not in set(no_design)]
    for a in no_design:
        # 无 design.md 无决策可抽：直接标 distilled 留痕跳过（对齐既有口径），
        # 否则 adr 条目永久 pending——回填无法收敛且排队门不释放
        ledger.mark(ADR_PREFIX + a, STATUS_DISTILLED)
    if no_design:
        # 留痕必须落盘：全部归档无 design 时下方批次循环不执行，循环内 save
        # 覆盖不到，台账文件会停在 pending（排队门被永久顶住）
        ledger.save()
    adr_batches = [
        with_design[i : i + BATCH_SIZE_MAX]
        for i in range(0, len(with_design), BATCH_SIZE_MAX)
    ]
    adr_total = len(adr_batches)
    adr_ok = 0
    adr_failed: list[dict] = []
    for i, batch in enumerate(adr_batches, 1):
        # 写段取蒸馏锁（同能力聚合批次）
        with knowledge_distill_lock(project_root):
            # 本批 run 前的脏文件基线（失败时差集回滚只清本车道触达文件）
            dirty_baseline = _knowledge_dirty_files(project_root)
            # 本批 run 前的违规基线：提交闸门只否决本轮新引入的违规（同自举段）
            before_violations = {str(v) for v in (validate(project_root) or [])}
            base_prompt = build_prompt("adr", batch=batch)
            run_id = f"kb-adr{i}-{int(time.time())}"
            try:
                spawn(base_prompt, run_id)
                ok, violations = _validate_with_repair(
                    project_root, validate, spawn, base_prompt, run_id,
                    before_violations=before_violations,
                )
            except Exception as e:  # noqa: BLE001 - 单批失败不阻塞后续批
                ok, violations = False, [f"run 派发/执行失败：{e}"]
            if ok:
                try:
                    commit(
                        project_root,
                        [KNOWLEDGE_DIR],
                        f"[fenix] knowledge: backfill adr batch {i}/{adr_total}",
                    )
                except Exception as e:  # noqa: BLE001
                    log.warning("knowledge", f"回填 ADR 批次 {i}/{adr_total} 提交失败（fail-open）：{e}")
                    uncommitted_keys.update(ADR_PREFIX + a for a in batch)
                else:
                    uncommitted_keys.clear()
                for a in batch:
                    ledger.mark(ADR_PREFIX + a, STATUS_DISTILLED, batch=i)
                adr_ok += 1
            else:
                # 回滚前把仍未落库的有效产出打回 pending（差集回滚保留在盘产出，
                # 同能力批次循环口径）
                stale = sorted(uncommitted_keys)
                for key in stale:
                    ledger.reset_pending(key)
                if stale:
                    _append_todo_fail_open(
                        project_root,
                        f"回填 ADR 批次 {i}/{adr_total} 回滚保留在盘产出（差集回滚"
                        f"只清本批新增脏路径），此前提交失败批次产出未落库，相关条目"
                        f"已打回 pending 待重入对账重做："
                        f"{', '.join(k.split(':', 1)[1] for k in stale[:5])}",
                        log,
                    )
                uncommitted_keys.clear()
                discard_knowledge_changes(project_root, before=dirty_baseline, log=log)
                for a in batch:
                    ledger.mark(ADR_PREFIX + a, STATUS_FAILED, batch=i)
                _append_todo_fail_open(
                    project_root,
                    f"回填 ADR 批次 {i}/{adr_total} 校验 {MAX_FIX_ROUNDS} 轮后仍失败"
                    f"（{len(batch)} 个归档），已回滚半成品：{violations[:3]}",
                    log,
                )
                adr_failed.append(
                    {"batch": i, "archives": batch, "violations": violations[:5]}
                )
                log.warning(
                    "knowledge",
                    f"回填 ADR 批次 {i}/{adr_total} 失败（{len(batch)} 归档），继续后续批次",
                )
        # 同能力批次循环：台账落盘失败按批留痕继续（fail-open），下一批 save
        # 重写全量台账可自愈
        try:
            ledger.save()
        except OSError as e:
            log.warning(
                "knowledge",
                f"回填 ADR 批次 {i}/{adr_total} 台账落盘失败（fail-open）：{e}",
            )

    # 收尾对账：仍有提交失败未落库的有效产出时，不能让台账停在 distilled
    # （内容在盘上未提交，后续任何一次回滚都会把它清掉而台账宣称已完成）——
    # 打回 pending 待重入重做，收敛与排队门保持关闭（code-review 3fd930cb6bbd）
    if uncommitted_keys:
        for key in sorted(uncommitted_keys):
            ledger.reset_pending(key)
        _append_todo_fail_open(
            project_root,
            "回填收尾仍有批次提交失败未落库，相关条目已打回 pending 待重入重做："
            f"{', '.join(k.split(':', 1)[1] for k in sorted(uncommitted_keys)[:5])}",
            log,
        )
        # 台账落盘失败不掀翻车道（fail-open，同批次循环口径）：条目重置已在内存
        # 且 todo 已留痕，收尾段落盘故障不让全部批次已跑完的车道沿调用链崩掉
        try:
            ledger.save()
        except OSError as e:
            log.warning("knowledge", f"回填收尾台账落盘失败（fail-open）：{e}")
        uncommitted_keys.clear()

    counts = ledger.counts()
    scale = scale_stats(project_root, log=log)
    converged = all(
        c[STATUS_PENDING] == 0 and c[STATUS_FAILED] == 0 for c in counts.values()
    )
    summary = {
        "triggered": True,
        "ok": not failed_batches and not adr_failed,
        "converged": converged,
        "batches_total": total,
        "batches_ok": len(ok_batches),
        "batches_failed": len(failed_batches),
        "adr_batches_total": adr_total,
        "adr_batches_ok": adr_ok,
        "adr_batches_failed": len(adr_failed),
        "adr_skipped_no_design": no_design,
        "failed": failed_batches,
        "adr_failed": adr_failed,
        "counts": counts,
        "scale": scale,
    }
    # 收敛报告缺盘不推翻台账事实（fail-open，对齐全文件防护纪律）：报告写盘
    # 的 OSError 不在全部批次跑完、台账已落盘之后沿调用链掀翻车道
    try:
        _write_report(project_root, summary)
    except OSError as e:
        log.warning("knowledge", f"回填收敛报告落盘失败（fail-open）：{e}")
    log.info(
        "knowledge",
        f"回填车道收敛汇报：能力批 {len(ok_batches)}/{total} 成功、"
        f"{len(failed_batches)} 失败；ADR 批 {adr_ok}/{adr_total} 成功、"
        f"{len(adr_failed)} 失败；规模 {scale}",
    )
    return summary


def _validate_with_repair(
    project_root: Path,
    validate: Callable,
    spawn: SpawnFn,
    base_prompt: str,
    run_id: str,
    repair_rounds: Optional[int] = None,
    before_violations: Optional[set[str]] = None,
) -> tuple[bool, list[str]]:
    """确定性校验 + 违规反馈修正环（≤MAX_FIX_ROUNDS 轮，对齐前置 SPEC 收尾校验）。

    修正环单实现（本车道与 knowledge_audit 共用，MAX_FIX_ROUNDS 同源）；
    ``repair_rounds`` 显式声明修正轮数上限：None = 缺省 ``MAX_FIX_ROUNDS``；
    0 = 只校验、不派发修正 run（无 run 语境的机械自修只验不改语义）。

    ``before_violations``（差集口径，对齐 knowledge_audit 的提交闸门）：本段
    run 前的违规快照。提供时修正反馈与最终否决只看「本轮新引入的违规」——
    真相源既有的无关违规（超 150 行硬顶页、marker 缺失、已落盘 ADR 三段正文
    被改写等 LLM 无法安全修复项）不再令整段/整批恒判失败空转，仍留在真相源
    走 audit 车道报告/待人工路径；只剩既有违规时也不再派发修正 run。缺省
    None 保留全量绝对判定旧口径（knowledge_audit 两处调用语义不变）。
    """
    max_rounds = MAX_FIX_ROUNDS if repair_rounds is None else repair_rounds
    violations = [str(v) for v in (validate(project_root) or [])]
    baseline = set(before_violations) if before_violations is not None else None
    rounds = 0
    while violations and rounds < max_rounds:
        feedback = violations if baseline is None else [
            v for v in violations if v not in baseline
        ]
        if baseline is not None and not feedback:
            # 只剩与本轮产出无关的既有违规：无新引入项可修，再派修正 run 必空转
            break
        rounds += 1
        # 修正 run 复用同一基础提示词（保留模式语境）+ 违规清单附加段
        spawn(
            base_prompt + "\n\n" + _violations_block(feedback),
            f"{run_id}-fix{rounds}",
        )
        violations = [str(v) for v in (validate(project_root) or [])]
    if baseline is None:
        return (not violations), violations
    new_violations = [v for v in violations if v not in baseline]
    return (not new_violations), new_violations


# 公开别名（core.knowledge_audit 复用，避免 import 私有名；须置于定义之后）
validate_with_repair = _validate_with_repair


def _write_report(project_root: Path, summary: dict) -> None:
    counts = summary.get("counts", {})
    cap_c = counts.get("capability", {})
    adr_c = counts.get("adr", {})
    failed = summary.get("failed", [])
    scale = summary.get("scale", {})
    lines = [
        "# 知识真相源存量回填汇报",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 能力批次总数：{summary.get('batches_total', 0)}"
        f"（成功 {summary.get('batches_ok', 0)} / 失败 {summary.get('batches_failed', 0)}）",
        f"- 能力页台账：distilled {cap_c.get(STATUS_DISTILLED, 0)} / "
        f"failed {cap_c.get(STATUS_FAILED, 0)} / "
        f"pending {cap_c.get(STATUS_PENDING, 0)}",
        f"- ADR 台账：distilled {adr_c.get(STATUS_DISTILLED, 0)} / "
        f"failed {adr_c.get(STATUS_FAILED, 0)} / "
        f"pending {adr_c.get(STATUS_PENDING, 0)}",
        f"- 真相源规模：{scale.get('domains', 0)} 域 / {scale.get('pages', 0)} 能力页 / "
        f"{scale.get('adrs', 0)} ADR / {scale.get('lines', 0)} 行",
        "",
    ]
    if failed:
        lines.append("## 失败批次（已登记 todo.md，重跑回填只重做失败条目）")
        lines.append("")
        for item in failed:
            lines.append(
                f"- 批次 {item['batch']}/{summary.get('batches_total', 0)}："
                f"{', '.join(item.get('capabilities', []))}"
            )
        lines.append("")
    adr_failed = summary.get("adr_failed", [])
    if adr_failed:
        lines.append("## ADR 失败批次（已登记 todo.md，重跑回填只重做失败条目）")
        lines.append("")
        for item in adr_failed:
            lines.append(
                f"- ADR 批次 {item['batch']}/{summary.get('adr_batches_total', 0)}："
                f"{', '.join(item.get('archives', []))}"
            )
        lines.append("")
    skipped = summary.get("adr_skipped_no_design", [])
    if skipped:
        lines.append(
            f"- 无 design.md 归档 {len(skipped)} 个，已标 distilled 留痕跳过："
            f"{', '.join(skipped)}"
        )
        lines.append("")
    atomic_write_text(project_root / REPORT_RELPATH, "\n".join(lines))


def main(argv: Optional[list[str]] = None) -> int:
    """手工激活入口：``python3 -m core.knowledge_backfill --project-root <主树>``。"""
    import argparse

    parser = argparse.ArgumentParser(description="知识真相源存量回填车道（手工激活）")
    parser.add_argument("--project-root", default=".", help="项目主树根目录")
    args = parser.parse_args(argv)
    # 手工激活是本车道唯一激活路径：不装配 logging 时 run_backfill 落
    # _NullLogger 静默替身，破坏性清理的删除前告警（自举清理未跟踪内容、
    # 域剪枝含已入库内容）、回滚半失败与批次提交失败 fail-open 留痕对操作者
    # 全部不可见。basicConfig（缺省 WARNING 级、stderr）+ 签名适配传入，
    # 与 daemon 挂载路径的留痕可见性对齐（code-review 37d8ce4af524）。
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    summary = run_backfill(
        Path(args.project_root).resolve(),
        logger=_StdLoggerAdapter(logging.getLogger("fenixd.knowledge_backfill")),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("ok", True) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
