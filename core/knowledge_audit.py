"""周期 audit 淘汰车道（add-knowledge-atlas-maintenance D2）。

每日一次（自然日语义，同自然日防重，对齐自省/回归调度先例）对真相源
``spec/knowledge/`` 全量体检五类病灶，分级处置：

- **机械项**（悬空溯源行、格式违规、ADR index 状态错位）确定性脚本直修直提交
  ``[fenix] knowledge: audit fix <摘要>``；
- **语义项**（矛盾、跨页重复）MUST NOT 脚本改写——转定向蒸馏 run（``audit.md``
  提示词）读两处冲突上下文后按增量蒸馏契约重写，允许「判无矛盾」零改动收场；
  重写失败登记 todo.md；
- **报告项**（超 150 行硬顶、ADR supersede 链断裂、ADR 目录未提交改动）进体检报告
  待人工。报告落 ``.fenix/knowledge_audit_report.md``，含规模趋势：总行数相对
  上次体检增长超 +10% 显式标「需精简」并给候选页清单。

挂载：``fenixd.py`` 主循环 300s 周期检查点调 ``knowledge_daily_check``（与自动
归档同款挂载）；门控 ``knowledge.audit_enabled``
（core/config.py get_knowledge_lane_config，缺省 True）。
（2026-09-29 graphify 关系图生成车道已取消下线：graph_enabled 键、run_graph
车道与 /api/knowledge/graph 下发端点一并移除，存量 graph/ 产物保留不清理。）
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Optional

from core.config import ConfigLoader
from core.knowledge_backfill import (
    append_todo_line,
    atomic_write_text,
    # re-export：本文件虽未直接调用，但测试替身与外部调用方以
    # ka.commit_pathspec 属性引用（code-review 6a2085a486ca 曾按「文件内
    # 无引用」误删，提交路径 AttributeError 被消费段 fail-open 吞掉后回归）
    commit_pathspec,
    default_spawn,
    discard_paths,
    knowledge_dirty_files,
    knowledge_distill_lock,
    load_knowledge_core,
    null_logger,
    resolve_commit,
    scale_stats,
    upsert_todo_line,
    validate_with_repair,
)
from core.timelib import parse_ts

# ── 常量 ─────────────────────────────────────────────────────────────────

REPORT_RELPATH = ".fenix/knowledge_audit_report.md"
STATE_RELPATH = ".fenix/knowledge_audit_state.json"
# 疑点台账（add-knowledge-audit-finding-ledger）：语义疑点判定历史与状态，
# 指纹为键、原子写；no-conflict 豁免 / 同批去重 / 升级待人工都以此为准据。
FINDINGS_RELPATH = ".fenix/knowledge_audit_findings.json"
PROMPT_PATH = Path(__file__).parent / "knowledge_prompts" / "audit.md"
KNOWLEDGE_DIR = "spec/knowledge"

# 单页 150 行硬顶（前置 SPEC 目录契约定稿，本车道只消费）
LINE_CAP = 150
# 规模趋势「需精简」阈值：总行数相对上次体检增长超 +10%
GROWTH_FLAG_RATIO = 0.10
# 语义项单轮转写 run 数上限（误报进 run 由 LLM 终判，但需封顶控成本）；
# 超出部分不静默丢弃，由 run_audit 转入体检报告待人工明细留痕
MAX_SEMANTIC_RUNS = 10

# escalated 超龄注记阈值天数（add-knowledge-audit-escalation-consumption 2.1，
# 缺省 7）：escalated 挂起超过该天数即对涉事知识页顶部写 disputed 机器可读
# 注记；knowledge.escalated_stale_days 可覆盖。缺省值与非法值回退的唯一事实
# 来源是 core/config.py 的 ConfigLoader.get_knowledge_lane_config（白名单解析，
# 非法值回退缺省 7）——此处不设本文件常量，避免两处 7 单侧修改静默漂移。
# 人工仲裁清单（本 SPEC 2.2：人工仲裁唯一入口）。.fenix/ 整体 gitignore
# （仅 todo.md/verify.yaml/config.template.yaml 白名单入库），人工本地裁决
# 不入库；条目形态 {fingerprint, decision, decided_at, note}。
# 白名单入库意图由 stray_wip 白名单脱落巡检机械核查（evo-whitelist-tracked-
# patrol 2.2：whitelist_untracked 信号，core/worktree_manager/stray_wip.py）
# ——被 ! 规则放行却不在 git 索引中即发 major 告警，「白名单应入库」约定与
# 执行机制互为引用，后来者可从任一侧找到另一侧。
ARBITRATION_RELPATH = ".fenix/knowledge_audit_arbitration.json"
# 仲裁决定合法值：no-conflict / false-positive → 判无矛盾语义、fixed → 纠偏
# 语义。消费段删条目即恢复自动复核（条目缺席，无豁免键留存），判定与 note
# 落状态文件 arbitration_history 留痕。
ARBITRATION_DECISIONS = ("fixed", "no-conflict", "false-positive")
# todo.md 升级登记聚合行固定前缀（同前缀替换不追加，1.3）与历史逐条行前缀
# （首跑 upsert 一并替换清理）
TODO_ESCALATED_AGG_PREFIX = "audit 疑点升级待人工（聚合）"
TODO_ESCALATED_LEGACY_PREFIX = "audit 疑点升级待人工："
# disputed 注记行解析（2.1）：不含 knowledge: 前缀——parse_marker/_MARKER_RE
# 取首个 knowledge: 匹配，disputed 前缀天然不冲突（不劫持 marker 解析）
_DISPUTED_RE = re.compile(r"<!--\s*disputed:\s*(.*?)-->")

_MARKER_RE = re.compile(r"<!--\s*knowledge:\s*(.*?)-->", re.DOTALL)
# 史前锚点形态（与 core.knowledge._GIT_ANCHOR_RE 同一定义，单一来源在该处；
# _scan_pages 无 core 语境，扫描侧只做形态校验，起始 ref 解析仍归校验器）
_GIT_ANCHOR_RE = re.compile(r"^git:([0-9a-f]{7,40})-\.\.(\d{4}-\d{2}-\d{2})$")
_ARCHIVE_REF_RE = re.compile(r"spec/archive/([A-Za-z0-9._-]+)")
_ADR_NAME_RE = re.compile(r"ADR-(\d{3})")
_STATUS_WORD_RE = re.compile(r"\b(accepted|superseded)\b")


# ── 状态文件（自然日防重 + 规模趋势基线） ────────────────────────────────


def _read_state(project_root: Path) -> dict:
    path = Path(project_root) / STATE_RELPATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(project_root: Path, state: dict) -> None:
    atomic_write_text(
        Path(project_root) / STATE_RELPATH,
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
    )


@contextmanager
def _file_write_lock(project_root: Path, filename: str):
    """``.fenix/<filename>`` 锁文件上的进程间互斥（flock）工厂。

    各车道文件（state / findings / arbitration）的读改写窗口共用同一锁实现：
    atomic_write_text 只保证单次写不撕裂，不保证读改写原子性，写方一律持锁
    重读盘上状态合并后再回写。锁文件自身无内容语义；各锁的竞态背景说明留在
    调用侧包装函数的 docstring。
    """
    import fcntl

    lock_dir = Path(project_root) / ".fenix"
    lock_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_dir / filename, os.O_RDWR | os.O_CREAT, 0o644)
    fh = os.fdopen(fd, "r+")  # noqa: SIM115 — 生命周期=with
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


@contextmanager
def _state_write_lock(project_root: Path):
    """状态文件读改写窗口的进程间互斥（flock，``.fenix/knowledge_audit_state.lock``）。

    同 _findings_write_lock 口径：daemon 与 dashboard --serve 两进程并发收尾
    （消费段写 arbitration_history / run_audit 写 last_scale / daily_check 写
    last_audit_date）时各持开局快照，后写者会用旧内存 state 整体覆盖先写者
    刚落盘的键：丢 last_audit_date 当日体检重复跑（语义 run 成本翻倍），丢
    arbitration_history 违反裁决事后可审计追溯。锁实现走 _file_write_lock
    单点口径。
    """
    with _file_write_lock(project_root, "knowledge_audit_state.lock"):
        yield


def _today() -> str:
    return time.strftime("%Y-%m-%d")


# ── 疑点台账（add-knowledge-audit-finding-ledger） ────────────────────────

# 条目状态五态（词表以此注释为文档，各读写处按字面量比较，不设独立常量）：
# suspected（复核中/待复核）→ exempt（no-conflict 且两页内容未变，初筛跳派）
# / fixed（重写提交纠偏）；superseded-in-batch（同批快照滞后重复，跳过）；
# escalated（连续两轮复核无确定性判定，挂起等人工——终态，人工删除台账条目
# 即消费清除，无自动恢复）。


def _load_findings_ledger(project_root: Path) -> dict:
    """读疑点台账（指纹 → 条目 dict）。缺失/损坏 fail-open 空台账。"""
    path = Path(project_root) / FINDINGS_RELPATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


@contextmanager
def _findings_write_lock(project_root: Path):
    """疑点台账读改写窗口的进程间互斥（flock，``.fenix/knowledge_audit_findings.lock``）。

    daemon 与 dashboard --serve 两进程同日竞跑体检收尾时各持开局快照，后写者
    会用旧内存台账整体覆盖先写者刚落盘的 verdict 与 page_hashes——no-conflict
    豁免键随之丢失、疑点被重复派发转写 run（code-review e13450339289，对齐
    BackfillLedger.save 的处置）。锁实现走 _file_write_lock 单点口径。
    """
    with _file_write_lock(project_root, "knowledge_audit_findings.lock"):
        yield


def _has_verdicts(entry: dict) -> bool:
    """条目是否已带确定性裁决（verdicts 非空列表）；形态损坏按无裁决计。"""
    verdicts = entry.get("verdicts")
    return isinstance(verdicts, list) and bool(verdicts)


def _save_findings_ledger(
    project_root: Path,
    ledger: dict,
    deleted_fingerprints: Optional[set[str]] = None,
    own_fingerprints: Optional[set[str]] = None,
) -> None:
    """疑点台账回写（持进程间文件锁 + 按指纹合并，对齐 BackfillLedger.save）。

    持锁重读盘上最新台账按指纹合并：仅一方持有的指纹直接纳入，两方都有的
    指纹取 ``updated_at`` 较新的一方（仅日期粒度，同日平手仅在「盘上已带
    裁决而本方未带」时保盘上，其余形态本方胜出），合并后再整文件原子回写
    ——并发的另一 run 刚落盘的判定与豁免键不再被本方旧快照覆盖丢失。
    ``deleted_fingerprints``：本方已删除的指纹（仲裁消费段）。按指纹合并
    只并键不删键，不显式剔除会让盘上另一进程写入的同指纹条目复活被删条目，
    人工仲裁决定随之失效。
    ``own_fingerprints``：本方本次真正动过的「己方指纹键」，传入后合并只取
    caller 台账里这些键，其余指纹一律不参与并集——run_audit 语义循环持开局
    快照反复回写（单轮最多 MAX_SEMANTIC_RUNS 个转写 run，可持续很久），循环
    期间他方仲裁消费可能已把快照里仍持有的 escalated 指纹从盘上台账删除；
    整快照并集会因盘上缺席（other is None）把它原样写回复活，只并己方键则
    无从复活。
    """
    with _findings_write_lock(project_root):
        merged = dict(_load_findings_ledger(project_root))
        for fp in tuple(deleted_fingerprints or ()):
            merged.pop(fp, None)
        if own_fingerprints is None:
            items = ledger.items()
        else:
            items = ((fp, ledger[fp]) for fp in own_fingerprints if fp in ledger)
        for fp, entry in items:
            other = merged.get(fp)
            if other is None:
                merged[fp] = entry
                continue
            entry_at = str(entry.get("updated_at", ""))
            other_at = str(other.get("updated_at", ""))
            if entry_at != other_at:
                if entry_at > other_at:
                    merged[fp] = entry
                continue
            # 同日平手：updated_at 由 _today() 生成、仅日期粒度，daemon 与
            # dashboard --serve 同日竞跑时本方可能仍持开局快照里的 suspected
            # 旧副本，而盘上另一 run 已为同指纹落盘裁决（updated_at 同为今天
            # 不分先后）——平手仅当「盘上已带裁决而本方未带」时保盘上（已
            # 裁决的 no-conflict 判定与豁免键不被旧快照覆盖丢失，code-review
            # e11faa0c441c）；其余形态（两侧都有/都无裁决）本方胜出——本方是
            # 本次 run 的最新视图，同一 run 此前落盘的中途副本也是更旧状态，
            # 终态不得被回退（否则 run 的末次保存恒输给自己轮内的中途落盘，
            # exempted_at/review_rounds/first_seen 等终态字段整体丢失）。
            if _has_verdicts(other) and not _has_verdicts(entry):
                continue
            merged[fp] = entry
        atomic_write_text(
            Path(project_root) / FINDINGS_RELPATH,
            json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        )


def _finding_fingerprint(finding: dict) -> str:
    """疑点指纹：sha256(kind + 两页 rel + 归一化规则行 + digits)。

    输入全部复用初筛的现成计算（_normalize_rule 与 _scan_semantic 同款 digits
    提取），不依赖 run 输出文本；两侧按 (page, 归一化规则行, digits) 排序后
    拼接，扫描顺序差异（甲乙互换）不产生新指纹。"""

    def _side(s: dict) -> tuple[str, str, str]:
        return (
            s["page"],
            _normalize_rule(s["rule"]),
            ",".join(re.findall(r"\d+(?:\.\d+)?", s["rule"])),
        )

    sa, sb = sorted((_side(finding["a"]), _side(finding["b"])))
    payload = "|".join((finding["kind"], *sa, *sb))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _page_hash(project_root: Path, rel: str) -> str:
    """页面现文 sha256（豁免键用全文哈希而非规则行指纹：同规则行在不同内容
    语境下判决会翻转，只有内容未变才豁免，内容一变即解冻重派）。"""
    return hashlib.sha256(
        _page_text_by_rel(project_root, rel).encode("utf-8")
    ).hexdigest()


def _new_finding_entry(finding: dict) -> dict:
    """新疑点入账（条目 schema 见设计：kind/pages/rules/page_hashes/verdicts/
    status/first_seen/updated_at；review_rounds 为升级轮次计数）。"""
    now = _today()
    return {
        "kind": finding["kind"],
        "pages": [finding["a"]["page"], finding["b"]["page"]],
        "rules": [finding["a"]["rule"], finding["b"]["rule"]],
        "page_hashes": {},
        "verdicts": [],
        "status": "suspected",
        "first_seen": now,
        "updated_at": now,
    }


def _record_verdict(
    entry: dict,
    verdict: str,
    commit: Optional[str] = None,
    page_hashes: Optional[dict] = None,
) -> None:
    """确定性判定入账：verdicts 追加判定/日期/提交，状态迁移，升级轮次清零。
    no-conflict 同时记录两页全文哈希（下次同指纹初筛的内容豁免键）。"""
    verdicts = entry.get("verdicts")
    if not isinstance(verdicts, list):
        # 台账条目人工编辑/旧版本可能缺 verdicts 键或类型损坏：就地补齐空
        # 列表走正常复核流程，不让单条损坏条目炸整轮 audit 车道。
        verdicts = []
        entry["verdicts"] = verdicts
    verdicts.append({"date": _today(), "verdict": verdict, "commit": commit})
    if page_hashes is not None:
        entry["page_hashes"] = page_hashes
    entry["status"] = "exempt" if verdict == "no-conflict" else "fixed"
    entry["review_rounds"] = 0
    entry["updated_at"] = _today()


# ── escalated 治理（add-knowledge-audit-escalation-consumption） ──────────


def _escalated_entries(ledger: dict) -> dict[str, dict]:
    """台账中 escalated 态条目（指纹 → 条目）；损坏条目跳过不炸车道。"""
    return {
        fp: e
        for fp, e in ledger.items()
        if isinstance(e, dict) and e.get("status") == "escalated"
    }


def _finding_age_days(first_seen, today=None) -> int:
    """自 first_seen 起算的龄期天数；日期串缺失/损坏按 0 计（不炸车道）。"""
    start_dt = parse_ts(str(first_seen or ""))
    end_dt = parse_ts(str(today or _today()))
    if start_dt is None or end_dt is None:
        return 0
    return max(0, (end_dt.date() - start_dt.date()).days)


def _escalated_summary(escalated: dict) -> Optional[dict]:
    """escalated 聚合汇总（1.2）：条数 + 最长龄期（自 first_seen 起算）。
    空台账返回 None，报告不出汇总节。"""
    if not escalated:
        return None
    today = _today()
    ages = [_finding_age_days(e.get("first_seen"), today) for e in escalated.values()]
    return {"count": len(ages), "max_age_days": max(ages) if ages else 0}


def _escalated_todo_line(escalated: dict) -> str:
    """todo.md 升级登记聚合行（1.3）：N 条待仲裁 + 最长龄期 + 仲裁清单路径
    （唯一人工入口）。空台账返回空串（upsert 按纯清理语义摘除残留行）。"""
    if not escalated:
        return ""
    summary = _escalated_summary(escalated)
    return (
        f"{TODO_ESCALATED_AGG_PREFIX}：{summary['count']} 条待人工仲裁"
        f"（最长龄期 {summary['max_age_days']} 天），请人工按指纹在 "
        f"{ARBITRATION_RELPATH} 登记仲裁决定（fingerprint/decision/decided_at/"
        f"note），框架检查点自动消费后恢复自动复核"
    )


def _disputed_line(since: str, fps: list[str]) -> str:
    """页顶 disputed 注记行（design D3 格式）。不含 knowledge: 前缀、不引用
    archive 路径（marker 三红线），fps 为指纹前缀 8 位列表（逗号连接无空格，
    排序保形——同页同条目集多次生成注记逐字节稳定）。"""
    return f"<!-- disputed: since={since} fps={','.join(sorted(fps))} -->"


def _disputed_targets(escalated: dict, stale_days: int) -> dict[str, str]:
    """超龄 escalated 条目 → 涉事页期望注记行（2.1）。

    龄期（自 first_seen 起算）严格大于 stale_days 才注记；同页多条超龄条目
    收敛为一条注记（since 取最早 first_seen，fps 并集）。"""
    by_page: dict[str, list[tuple[str, str]]] = {}
    today = _today()
    for fp, entry in escalated.items():
        if _finding_age_days(entry.get("first_seen"), today) <= stale_days:
            continue
        for rel in entry.get("pages") or []:
            if isinstance(rel, str) and rel:
                by_page.setdefault(rel, []).append(
                    (str(entry.get("first_seen") or ""), str(fp)[:8])
                )
    return {
        rel: _disputed_line(
            min((seen for seen, _ in items if seen), default="") or today,
            [fp for _, fp in items],
        )
        for rel, items in by_page.items()
    }


def _annotation_insert_index(lines: list[str]) -> int:
    """注记插入位（design D3）：H1 与既有 knowledge marker 之后、独立成行。
    H1 取其行的下一行；marker 取注释块结束行（``-->`` 所在行）的下一行——
    marker 契约允许跨行（spec/knowledge/README.md 展示的多行形态，_MARKER_RE
    亦 DOTALL 容跨行），按「起始行 i+1」会把注记插进注释块内部、被
    _parse_marker 当作 marker 字段文本解析出垃圾字段。二者取较大者；都不在
    场（导航页等）插页首。"""
    pos = 0
    for i, ln in enumerate(lines[:10]):
        if ln.startswith("# "):
            pos = i + 1
    text = "\n".join(lines)
    m = _MARKER_RE.search(text)
    if m:
        start_line = text.count("\n", 0, m.start())
        if start_line < 10:  # 既有口径：只认页首 10 行内的 marker
            pos = max(pos, text.count("\n", 0, m.end()) + 1)
    return pos


def _sync_disputed_annotations(
    project_root: Path,
    desired: dict[str, str],
    restrict_pages=None,
) -> tuple[list[str], list[str]]:
    """把涉事页顶 disputed 注记对齐到期望态（写入/更新/摘除）。

    ``desired`` 为页 rel → 期望注记行；不在期望态的受限页摘除既有注记（消费
    摘除 / 台账清零自愈共用）。``restrict_pages`` 限定可触碰页（消费段传涉事
    页保持轻量；缺省不限）。写前查 150 行硬顶（超限跳过留痕不写，返回值第二
    元）；既有注记为原位替换（行数不变，无硬顶问题）。返回 ``(改写页, 跳过页)``。
    """
    pages = set(desired)
    if restrict_pages is not None:
        # 并集而非交集：受限页是「允许触碰」上限，desired 为空（消费摘除 /
        # 台账清零自愈）时受限页上的既有注记仍须被摘除——交集会让摘除场景
        # 空转（desired 空集 × restrict = 空集，注记永久残留）。
        pages |= set(restrict_pages)
    changed: list[str] = []
    skipped: list[str] = []
    for rel in sorted(pages):
        path = Path(project_root) / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        idx = next((i for i, ln in enumerate(lines) if _DISPUTED_RE.search(ln)), None)
        new_line = desired.get(rel)
        # 摘除/更新按行内注记子串操作而非盲删/整行覆盖：_DISPUTED_RE 是行内
        # 子串匹配，注记与正文同行（人工编辑/外部工具写入）时整行删除会连带
        # 丢正文、整行覆盖会把正文抹成纯注记行。仅当注记独占整行（strip 后与
        # 匹配全等，框架写入侧形态）才整行删/换。
        if new_line is None:
            if idx is None:
                continue
            old = lines[idx]
            matched = _DISPUTED_RE.search(old).group(0)
            if old.strip() == matched:
                del lines[idx]
            else:
                # 只剔除行内注记子串，不连带丢同行正文；顺带剥掉注记摘除后
                # 露出的行尾空白（免得给下轮 format 扫描留脏行）。
                lines[idx] = old.replace(matched, "").rstrip()
        elif idx is not None:
            old = lines[idx]
            matched = _DISPUTED_RE.search(old).group(0)
            if old.strip() == new_line:
                continue
            if old.strip() == matched:
                lines[idx] = new_line
            else:
                # 只替换行内注记子串，保留同行正文
                lines[idx] = old.replace(matched, new_line)
        else:
            # 150 行硬顶（红线三）：写入前查行数，新增一行不得越顶
            if len(lines) + 1 > LINE_CAP:
                skipped.append(rel)
                continue
            lines.insert(_annotation_insert_index(lines), new_line)
        new_text = "\n".join(lines)
        if text.endswith("\n"):
            new_text += "\n"
        atomic_write_text(path, new_text)
        changed.append(rel)
    return changed, skipped


def _load_arbitration_list(project_root: Path) -> list[dict]:
    """读人工仲裁清单（fail-open：缺失/损坏/形态不符 → 空清单）。裸数组或
    ``{"decisions": [...]}`` 两种形态均可（人工手写容错）。"""
    path = Path(project_root) / ARBITRATION_RELPATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):
        data = data.get("decisions")
    if not isinstance(data, list):
        return []
    return [e for e in data if isinstance(e, dict)]


@contextmanager
def _arbitration_write_lock(project_root: Path):
    """仲裁清单读改写窗口的进程间互斥（flock，``.fenix/knowledge_audit_arbitration.lock``）。

    同 _findings_write_lock 口径：daemon 与 dashboard --serve 两进程并发消费
    不同条目时各持开局快照，后写者的 kept 整体覆盖先写者刚落盘的剔除结果，
    已消费条目被写回清单且此后每轮 300s 检查点因台账条目已删恒走「指纹未知」
    warning 分支、consumed 为空不回写，残留条目无法被框架自动摘除
    （code-review f619e62ef214，对齐 _findings_write_lock 的处置）。锁实现走
    _file_write_lock 单点口径。
    """
    with _file_write_lock(project_root, "knowledge_audit_arbitration.lock"):
        yield


def _arbitration_entry_key(entry: dict) -> str:
    """仲裁条目同一性键（规范化 JSON）：消费剔除按完整条目对账而非仅指纹——
    同指纹可并存多条（合法 decision 已消费、非法 decision 跳过留痕），按指纹
    剔除会误吞跳过留痕条目。"""
    return json.dumps(entry, ensure_ascii=False, sort_keys=True)


def _save_arbitration_list(project_root: Path, consumed: list[dict]) -> None:
    """仲裁清单回写（持进程间文件锁 + 按条目合并，对齐 _save_findings_ledger）。

    持锁重读盘上最新清单、只剔除本方已消费条目（按 _arbitration_entry_key 对
    账）后整文件原子回写：另一进程并发消费刚剔除的条目不复活（盘上已缺席），
    另一进程保留/人工新写入的条目不丢失——消除两进程并发消费时后写者 kept
    整体覆盖先写者的 last-writer-wins。本方跳过留痕条目不在此回添：kept ⊆
    开局快照，盘上仍在场的已随盘上清单保留，盘上已缺席的（他方已消费或人工
    已移除）回添即复活已消费条目。
    """
    with _arbitration_write_lock(project_root):
        consumed_keys = {_arbitration_entry_key(e) for e in consumed}
        merged = [
            e
            for e in _load_arbitration_list(project_root)
            if _arbitration_entry_key(e) not in consumed_keys
        ]
        atomic_write_text(
            Path(project_root) / ARBITRATION_RELPATH,
            json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        )


def consume_arbitration(
    project_root,
    logger=None,
    config: Optional[dict] = None,
) -> dict:
    """人工仲裁清单独立消费段（2.2）。

    由 knowledge_daily_check 在 audit_enabled 门控后、自然日防重短路前调用：
    不依赖当日体检是否已跑，每次 300s 检查点都执行，人工写入当日生效。命中
    台账 escalated 指纹且 decision 合法 → 判定与人工 note 落状态文件历史留痕
    （arbitration_history，条目随即删除、_record_verdict 的就地变更不落持久层，
    故不调用）→ 删台账条目（条目缺席即恢复该页对自动复核，既有
    _new_finding_entry 重建语义，零新机制）→ 摘涉事页 disputed 注记并走既有
    ``[fenix] knowledge`` 提交路径自提交（摘除残留不成为下一轮 carryover
    告警源）。非法 decision / 未知指纹 / 非 escalated 状态：跳过留痕，不抛错
    不阻断审计。未命中零写零提交（保持周期执行的轻量）。

    挂载现状：本段当前仅由 daemon 300s 检查点单进程串行调用（fenixd.py
    knowledge 检查点，dashboard 未挂载本车道）；本文件的进程间锁与按指纹
    合并回写按「将来可能挂载 dashboard --serve 第二写入方」防御性设计，
    非现存并发事实。
    """
    project_root = Path(project_root)
    log = logger or null_logger()
    decisions = _load_arbitration_list(project_root)
    if not decisions:
        return {"triggered": False, "consumed": 0}
    ledger = _load_findings_ledger(project_root)
    consumed: list[dict] = []
    kept: list[dict] = []
    pages_touched: set[str] = set()
    for item in decisions:
        fp = str(item.get("fingerprint") or "")
        decision = str(item.get("decision") or "")
        if decision not in ARBITRATION_DECISIONS:
            log.warning(
                "knowledge",
                f"仲裁清单条目 decision 非法（{decision!r}），跳过留痕："
                f"fp={fp[:8]} note={item.get('note')!r}",
            )
            kept.append(item)
            continue
        entry = ledger.get(fp)
        if not isinstance(entry, dict) or entry.get("status") != "escalated":
            log.warning(
                "knowledge",
                f"仲裁清单条目指纹未知或非 escalated 状态，跳过留痕：fp={fp[:8]}",
            )
            kept.append(item)
            continue
        # 删条目前不留状态迁移：条目随即删除且 _save_findings_ledger 按
        # deleted_fingerprints 显式剔除同指纹，_record_verdict 的就地变更不落
        # 任何持久层（死调用）；判定与人工 note 改落状态文件历史留痕（见下）。
        # 消费 = 台账条目删除，缺席即恢复自动复核（页对矛盾仍在时下一轮 audit
        # 以新 suspected 条目重开）
        pages_touched |= {
            p for p in (entry.get("pages") or []) if isinstance(p, str)
        }
        del ledger[fp]
        consumed.append(item)
        log.info(
            "knowledge",
            f"仲裁清单消费：fp={fp[:8]} decision={decision} "
            f"note={item.get('note')!r}，台账条目已删除，恢复自动复核",
        )
    if not consumed:
        return {"triggered": False, "consumed": 0, "skipped": len(kept)}
    # 仲裁判定留痕：台账条目与清单条目均已删除，_record_verdict 的判定不落盘
    # ——判定/人工 note/指纹落状态文件历史（封顶 50 条最旧先出），裁决依据
    # 事后可审计追溯。持 _state_write_lock 重读盘上状态再合并回写（对齐
    # _save_findings_ledger 口径）：daemon 与 dashboard --serve 两进程并发
    # 消费/收尾时，后写者的开局快照不覆盖先写者刚落盘的历史与其他键。
    with _state_write_lock(project_root):
        state = _read_state(project_root)
        hist = state.get("arbitration_history")
        hist = (
            [e for e in hist if isinstance(e, dict)]
            if isinstance(hist, list)
            else []
        )
        hist.extend(
            {
                "fingerprint": str(item.get("fingerprint") or ""),
                "decision": str(item.get("decision") or ""),
                "note": item.get("note"),
                "decided_at": item.get("decided_at"),
                "consumed_at": _today(),
            }
            for item in consumed
        )
        state["arbitration_history"] = hist[-50:]
        _write_state(project_root, state)
    # 只删条目不改他键：own_fingerprints 传空集，开局快照（上方 _load 得到的
    # ledger）不参与并集、仅 deleted_fingerprints 生效——快照里他方已消费/
    # 删除的 escalated 指纹不因盘上缺席被本方原样写回复活、人工仲裁决定不被
    # 静默作废（同 run_audit 语义循环的己方指纹键合并纪律）。
    _save_findings_ledger(
        project_root,
        ledger,
        deleted_fingerprints={
            str(item.get("fingerprint") or "") for item in consumed
        },
        own_fingerprints=set(),
    )
    _save_arbitration_list(project_root, consumed)
    # 摘注记按消费后台账现状重算期望态、只限涉事页：同页其余 escalated 条目
    # 仍超龄在册时注记改写（fps 收敛）而非误摘。期望态从盘上台账重读（对齐
    # run_audit 收尾重读口径）：本地 ledger 是本段开局快照，将来挂载
    # dashboard --serve 第二写入方时，同页他方在册而快照缺失的 escalated 条目
    # 若按快照重算会被当「该页无超龄条目」整条误摘。
    changed: list[str] = []
    core = load_knowledge_core()
    if core is None:
        log.warning(
            "knowledge",
            "仲裁消费后注记摘除跳过：core.knowledge 不可用（下一轮 audit 补同步）",
        )
    else:
        cfg = ConfigLoader.get_knowledge_lane_config(config or {})
        desired = _disputed_targets(
            _escalated_entries(_load_findings_ledger(project_root)),
            cfg["escalated_stale_days"],
        )
        # 写段取蒸馏锁（同 run_audit 注记同步段口径）：_sync_disputed_annotations
        # 是对知识页的读盘-改行-整页原子回写，仲裁消费挂在 300s 检查点上、与
        # 归档事件触发的蒸馏 run 并发时，消费段基于读时快照的回写会覆盖蒸馏
        # run 刚写入的页面内容（丢失蒸馏产出），反之消费段的注记变更也会被蒸
        # 馏 run 随后回写丢弃（code-review b018e793634e）。本调用链
        # （knowledge_daily_check → 本段）不持蒸馏锁，无自阻塞。
        with knowledge_distill_lock(project_root):
            changed, _skipped = _sync_disputed_annotations(
                project_root, desired, restrict_pages=pages_touched
            )
            if changed:
                try:
                    resolve_commit(core)(
                        project_root,
                        [KNOWLEDGE_DIR],
                        f"[fenix] knowledge: audit disputed 注记摘除（{len(changed)} 页）",
                    )
                except Exception as e:  # noqa: BLE001 - 提交失败 fail-open（内容已在盘上）
                    log.warning("knowledge", f"仲裁摘注记提交失败（fail-open）：{e}")
    return {
        "triggered": True,
        "consumed": len(consumed),
        "skipped": len(kept),
        "annotations_removed": len(changed),
    }


# ── 每日检查点（fenixd 主循环挂载入口） ──────────────────────────────────


def knowledge_daily_check(
    project_root,
    config: Optional[dict] = None,
    logger=None,
    audit_lane: Optional[Callable] = None,
) -> dict:
    """daemon 主循环 300s 周期调用的每日检查点（audit 车道）。

    门控与防重语义：
    - ``knowledge.audit_enabled`` 门控；
    - 车道按状态文件的自然日戳同自然日防重（只跑一次）；
    - 禁用或当日已跑 → 静默返回，零日志噪音（禁用跳过场景）；
    - 车道抛异常记日志不更新日戳（下一周期重试），不中断主循环（挂载侧同款
      try/except）。
    """
    project_root = Path(project_root)
    log = logger or null_logger()
    cfg = ConfigLoader.get_knowledge_lane_config(config or {})
    audit_enabled = cfg["audit_enabled"]
    if not audit_enabled:
        return {"triggered": False, "reason": "disabled"}
    state = _read_state(project_root)
    today = _today()
    results: dict[str, dict] = {}

    # 仲裁清单独立消费段（2.2）挂防重短路之前：若挂 escalated-skip 分支（audit
    # 车道内），当日体检已跑后防重会整段短路车道，人工写入要等次日体检才被
    # 消费，「当日生效」不成立；独立消费段不依赖当日体检是否已跑，每次 300s
    # 检查点都执行。异常记日志不阻断审计主车道。
    try:
        arb = consume_arbitration(project_root, logger=log, config=config)
    except Exception as e:  # noqa: BLE001 - 消费段异常不中断主循环
        log.error("knowledge", f"仲裁清单消费段执行失败（不阻断审计）：{e}")
        arb = {"triggered": False, "error": str(e)}
    if arb.get("triggered"):
        results["arbitration"] = arb

    if state.get("last_audit_date") != today:
        try:
            lane = audit_lane or run_audit
            res = lane(project_root, logger=log, config=config) or {}
        except Exception as e:  # noqa: BLE001 - 周期车道异常不中断主循环
            log.error("knowledge", f"audit 车道执行失败（下周期重试）：{e}")
            res = {"ok": False, "error": str(e)}
        results["audit"] = res
        # 前置未就绪的跳过不落日戳（core 缺失 / 知识目录尚未建好，前置就绪
        # 后当日即可补跑）；正常体检（含零病灶/机械修复）落日戳，同自然日只跑
        # 一次。
        if res.get("ok", False) and res.get("reason") not in (
            "knowledge-core-unavailable",
            "no-knowledge-dir",
        ):
            # 回写前持 _state_write_lock 重读盘上状态合并（本 SPEC 3.2）：车道
            # 内部（run_audit）可能已写 last_scale 等键，本地 state 是检查点
            # 开头的陈旧副本，直接回写会把它覆盖丢失（规模趋势「上次 X 行」
            # 基线随之失效）；持锁重读再改写，另一进程并发落盘的键同样不丢。
            with _state_write_lock(project_root):
                state = _read_state(project_root)
                state["last_audit_date"] = today
                _write_state(project_root, state)

    return {"triggered": bool(results), "today": today, "results": results}


# ── 页面收集与病灶扫描 ───────────────────────────────────────────────────


def _collect_pages(project_root: Path) -> list[dict]:
    """收集能力页与导航页（relpath + 文本）。graph/ 产物非真相源本体，跳过。"""
    kdir = Path(project_root) / KNOWLEDGE_DIR
    pages: list[dict] = []
    if not kdir.is_dir():
        return pages
    candidates = [kdir / "index.md"]
    dom = kdir / "domains"
    if dom.is_dir():
        candidates.extend(p for p in sorted(dom.rglob("*.md")))
    for path in candidates:
        if not path.is_file():
            continue
        rel = path.relative_to(project_root).as_posix()
        pages.append(
            {
                "rel": rel,
                "path": path,
                "text": path.read_text(encoding="utf-8", errors="replace"),
            }
        )
    return pages


def _parse_marker(text: str) -> Optional[dict]:
    m = _MARKER_RE.search(text)
    if not m:
        return None
    fields: dict[str, str] = {}
    for token in m.group(1).split():
        if "=" in token:
            k, _, v = token.partition("=")
            fields[k] = v
    return fields if fields else None


def _existing_archives(project_root: Path) -> set[str]:
    adir = Path(project_root) / "spec" / "archive"
    return {p.name for p in adir.iterdir() if p.is_dir()} if adir.is_dir() else set()


def _source_base(src: str) -> str:
    """marker sources 项归一为归档基名，供与 ``_existing_archives`` 的基名集合
    比对。真相源契约里 sources 是全路径（``spec/archive/<名>``，core.knowledge
    校验器强制该前缀），不归一直接比对会恒判悬空 → ``_clean_sources`` 把
    sources 清空 → 校验报 marker 非法 → 整轮机械自修被回滚。"""
    return Path(src.strip().rstrip("/")).name


def _trailing_ws_dirty(ln: str) -> bool:
    """行尾是否带需清理的脏空白。

    Markdown 行尾恰好两个空格是硬换行语义（可见内容形态，非脏空白）：格式
    扫描对其豁免、机械清理原样保留；其余尾随空白（单个空格、3 个及以上连续
    空格、制表符等）按脏空白扫描与剥除。硬换行豁免只适用于有内容的行——
    整行仅两个空格的纯空白行不含任何可见内容、无硬换行语义可言，统一按脏
    空白清理。扫描与清理共用同一判定，避免出现「扫得出修不掉」的永久挂起
    格式页。
    """
    if not ln.strip():
        # 纯空白行：非空（rstrip 后为空但原行有字符）即脏空白，不享硬换行豁免
        return bool(ln)
    tail = ln[len(ln.rstrip()) :]
    return tail not in ("", "  ")


def _scan_pages(project_root: Path) -> dict:
    """五类病灶中的页级扫描：悬空溯源（①② 机械）、超行数（报告）、格式。"""
    pages = _collect_pages(project_root)
    archives = _existing_archives(project_root)
    dangling_pages: list[dict] = []  # 机械：页 rel → 待删行/待删 sources
    dangling_suspect: list[str] = []  # 报告：带尾缀（句点/.md）疑似悬空引用，不机械删行
    overcap: list[dict] = []  # 报告：超 150 行
    format_pages: list[str] = []  # 机械：尾随空白/缺 EOF 换行
    no_marker: list[str] = []  # 报告：能力页 marker 缺失/不可解析（待人工）
    for page in pages:
        text = page["text"]
        lines = text.splitlines()
        if len(lines) > LINE_CAP:
            overcap.append({"rel": page["rel"], "lines": len(lines)})
        is_capability = "/domains/" in page["rel"] and Path(page["rel"]).name != "_domain.md"
        marker = _parse_marker(text)
        if is_capability and marker is None:
            no_marker.append(page["rel"])
        # 悬空溯源：marker sources + 正文 spec/archive 引用
        drop_lines: list[int] = []
        missing_sources: list[str] = []
        if marker and marker.get("sources"):
            names = [s for s in re.split(r"[,，]", marker["sources"]) if s]
            if (marker.get("origin") or "archive") == "prehistoric":
                # 史前页 sources 是 git 区间锚点（origin=prehistoric，core.knowledge
                # 校验器支持，无对应归档目录）：按锚点形态校验，与
                # validate_knowledge 的 prehistoric 分支同口径（起始 ref 是否可解析
                # 由校验器带预算降级处理，扫描侧不查）。仍按归档基名比对会把每个
                # 合法锚点判悬空，_apply_mechanical 保留原值后逐日产「marker
                # sources 全部悬空待人工」误报并推高 pending_manual。
                missing_sources = [s for s in names if not _GIT_ANCHOR_RE.match(s.strip())]
            else:
                missing_sources = [s for s in names if _source_base(s) not in archives]
        # marker 跨度行不进 drop_lines（code-review 0b78fcd778e3）：marker 的
        # sources 项是全路径 ``spec/archive/<名>``（core.knowledge 校验器强制
        # 该前缀），归档目录被删后 marker 行自身就会命中 _ARCHIVE_REF_RE；若
        # 按行删除会把 marker（或其 sources 字段）整行移除，validate_knowledge
        # 随即报「marker 缺失/字段非法」新违规，run_audit 的提交闸门会把本轮
        # 全部机械修复回滚。marker 行的 sources 悬空剔除只交给
        # _apply_mechanical._clean_sources 按字段粒度处理（sources 全悬空保留
        # 原值转待人工的防御才真正可达）。
        mk = _MARKER_RE.search(text)
        marker_lines: set[int] = set()
        if mk:
            marker_lines = set(
                range(
                    text.count("\n", 0, mk.start()),
                    text.count("\n", 0, mk.end()) + 1,
                )
            )
        for i, ln in enumerate(lines):
            if i in marker_lines:
                continue
            for m in _ARCHIVE_REF_RE.finditer(ln):
                name = m.group(1).strip("\"'`")
                # 捕获字符类含 ``.``：正文以 ASCII 句点收尾会捕获尾点、
                # ``spec/archive/foo.md`` 会带 .md 后缀，直接对归档基名集合
                # （无点号/无 .md）比对即误判悬空 → _apply_mechanical 把整行
                # 删除并随 audit fix 自动提交，误删内容只能靠 git 历史找回。
                # 归一（剥尾随点号与 .md 后缀）后再比对：归一后命中视为有效
                # 引用；仍不中且捕获带上述尾缀（标点污染与真悬空不可分）时
                # 降级为报告项，不做机械删行。
                bare = name.rstrip(".")
                if bare.endswith(".md"):
                    bare = bare[: -len(".md")]
                if bare in archives:
                    continue
                if name != bare:
                    dangling_suspect.append(
                        f"{page['rel']}：正文 spec/archive 引用带尾缀（句点/.md），"
                        f"疑似悬空待人工核实：{m.group(0)}"
                    )
                    continue
                drop_lines.append(i)
                break
        if missing_sources or drop_lines:
            dangling_pages.append(
                {
                    "rel": page["rel"],
                    "path": page["path"],
                    "drop_lines": drop_lines,
                    "missing_sources": missing_sources,
                }
            )
        # 格式违规（机械可修）：行尾脏空白 / 文件缺结尾换行（行尾恰好两个空格
        # 属 Markdown 硬换行语义，_trailing_ws_dirty 豁免，机械清理同样保留）
        if any(_trailing_ws_dirty(ln) for ln in lines) or (
            text and not text.endswith("\n")
        ):
            format_pages.append(page["rel"])
    return {
        "pages": pages,
        "dangling": dangling_pages,
        "dangling_suspect": dangling_suspect,
        "overcap": overcap,
        "format": format_pages,
        "no_marker": no_marker,
    }


def _adr_entry_status(text: str) -> Optional[str]:
    """ADR 条目头部状态：Superseded by: 在场 → superseded；status: 行次之。"""
    if re.search(r"^Superseded by:", text, re.MULTILINE | re.IGNORECASE):
        return "superseded"
    m = re.search(r"^status:\s*(accepted|superseded)\b", text, re.MULTILINE | re.IGNORECASE)
    return m.group(1).lower() if m else None


def _adr_status_slot(ln: str) -> Optional[tuple[int, int, str]]:
    """定位 ADR index 行的状态槽位，返回 ``(start, end, 小写状态词)``；无则 None。

    状态比对与改写都必须锚定状态槽位本身：整行首次出现的匹配会被编号链接
    slug 或标题/摘要里的 accepted/superseded 字样抢走——比对错位、改写污染
    标题，且大写形式能被小写化的 search 命中却不会被大小写敏感的 sub 替换。
    - 表格行（``|`` 分列）：状态列整列即状态词（真实 index 列序「编号、状态、
      摘要」），取内容恰为 accepted/superseded 的列；
    - 非表格行（列表项「— accepted」尾缀形态）：状态词缀在行尾，取整行
      **末次**出现，同理避开标题用词。
    """
    if "|" in ln:
        offset = 0
        for col in ln.split("|"):
            if col.strip().lower() in ("accepted", "superseded"):
                m = _STATUS_WORD_RE.search(col.lower())
                return (offset + m.start(), offset + m.end(), m.group(1))
            offset += len(col) + 1
        return None
    matches = list(_STATUS_WORD_RE.finditer(ln.lower()))
    if not matches:
        return None
    m = matches[-1]
    return (m.start(), m.end(), m.group(1))


def _adr_file_exists(adr_dir: Path, name: str) -> bool:
    """ADR-\\d{3} 引用在盘上的存在性：精确名或 slug 形态前缀文件
    （如 ADR-015-add-knowledge-atlas.md）任一命中即算在盘。只按精确名比对会
    把 slug 命名的真实文件判成断链（ADR-015/019/034 三条永久误报实况）。"""
    if (adr_dir / f"{name}.md").is_file():
        return True
    return any(adr_dir.glob(f"{name}-*.md"))


def _scan_adrs(project_root: Path) -> dict:
    """ADR 病灶：supersede 链断裂（报告）、index 状态与条目头不一致（机械对齐）、
    ADR 目录未提交改动（报告，不按条目状态过滤）。"""
    adr_dir = Path(project_root) / KNOWLEDGE_DIR / "adr"
    broken_chain: list[str] = []
    status_mismatch: list[dict] = []
    entry_status: dict[str, str] = {}
    if adr_dir.is_dir():
        for path in sorted(adr_dir.glob("ADR-*.md")):
            text = path.read_text(encoding="utf-8", errors="replace")
            mm = re.match(r"ADR-(\d{3})", path.stem)
            name = f"ADR-{mm.group(1)}" if mm else path.stem
            m = re.search(r"^Superseded by:\s*(ADR-\d{3})", text, re.MULTILINE | re.IGNORECASE)
            if m and not _adr_file_exists(adr_dir, m.group(1)):
                broken_chain.append(f"{path.stem} 的 Superseded by 指向不存在的 {m.group(1)}")
            status = _adr_entry_status(text)
            if status:
                entry_status[name] = status
    index_path = adr_dir / "index.md" if adr_dir.is_dir() else None
    if index_path and index_path.is_file():
        index_lines = index_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, ln in enumerate(index_lines):
            nm = _ADR_NAME_RE.search(ln)
            slot = _adr_status_slot(ln)
            if not nm or not slot:
                continue
            name = f"ADR-{nm.group(1)}"
            expected = entry_status.get(name)
            if expected and expected != slot[2]:
                status_mismatch.append(
                    {"line_no": i, "name": name, "wrong": slot[2], "expected": expected}
                )
    adr_dirty: list[str] = []
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--", f"{KNOWLEDGE_DIR}/adr"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            # 固定 UTF-8 + replace（仓库 subprocess 惯例）：text=True 缺省走
            # locale strict 解码，ADR 目录混入非 UTF-8 文件名时
            # UnicodeDecodeError 会穿透本函数与 run_audit，令当日体检与语义
            # 转写整体停摆且每 300s 检查点恒失败刷屏。
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            adr_dirty = [
                ln for ln in proc.stdout.strip().splitlines() if ln.strip()
            ]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {
        "broken_chain": broken_chain,
        "status_mismatch": status_mismatch,
        "adr_dirty": adr_dirty,
    }


def _rule_lines(text: str) -> list[str]:
    """提取 `## 规则` 段（或唯一二级标题段）下的列表项行。"""
    lines = text.splitlines()
    rules: list[str] = []
    in_rules = False
    for ln in lines:
        if ln.startswith("## "):
            in_rules = "规则" in ln
            continue
        if ln.startswith("# "):
            in_rules = False
        if in_rules and re.match(r"^\s*[-*]\s+", ln):
            rules.append(re.sub(r"^\s*[-*]\s+", "", ln).strip())
    return rules


def _normalize_rule(line: str) -> str:
    return re.sub(r"[^0-9a-zA-Z一-鿿]", "", line)


def _scan_semantic(pages: list[dict]) -> list[dict]:
    """矛盾/重复初筛（宁松勿紧）：同主题词不同数值 → 矛盾候选；跨页近似/相同
    规则 → 重复候选。LLM 在转写 run 里终判，误报由「判无矛盾」零改动收场。
    返回全部候选（不截断）：单轮转写条数上限由 run_audit 按 MAX_SEMANTIC_RUNS
    截断，并把溢出候选转入待人工明细，不在本函数静默丢弃。"""
    entries: list[dict] = []
    for page in pages:
        for rule in _rule_lines(page["text"]):
            norm = _normalize_rule(rule)
            if len(norm) < 4:
                continue  # 过短碎片（如「禁止。」）不参与配对
            subject = re.split(r"[：:]", rule, maxsplit=1)[0]
            digits = tuple(re.findall(r"\d+(?:\.\d+)?", rule))
            entries.append(
                {
                    "page": page["rel"],
                    "rule": rule,
                    "norm": norm,
                    "subject": _normalize_rule(subject)[:12],
                    "digits": digits,
                }
            )
    findings: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()
    # [fenix-ignore:1a3eaa1a3dc9] 规模敏感性提示非现行缺陷（页数受 150 行硬顶约束）；建议的 (subject, digits) 桶化不可证语义等价——same_text 配对不要求同 subject（_normalize_rule 剥冒号，"限速：60" 与 "限速 60" 同 norm 异 subject）、fuzzy_dup 亦不要求同 subject，按该键建桶会漏配对，全量等价桶化需 norm/subject/digits 三族键加配对序复原，非低风险局部改动。
    for i, a in enumerate(entries):
        for b in entries[i + 1 :]:
            if a["page"] == b["page"] and a["norm"] == b["norm"]:
                continue  # 同页逐字重复不算病灶
            same_text = a["norm"] == b["norm"]
            similar = (
                a["norm"] != b["norm"]
                and a["subject"]
                and a["subject"] == b["subject"]
                and a["digits"]
                and b["digits"]
                and a["digits"] != b["digits"]
            )
            fuzzy_dup = (
                not same_text
                and a["page"] != b["page"]
                and a["digits"]
                and b["digits"]
                and a["digits"] == b["digits"]
                and difflib.SequenceMatcher(None, a["norm"], b["norm"]).ratio() >= 0.9
            )
            kind = None
            if same_text and a["page"] != b["page"]:
                kind = "duplicate"
            elif similar:
                kind = "contradiction"
            elif fuzzy_dup:
                kind = "duplicate"
            if kind is None:
                continue
            pair = tuple(sorted([a["page"] + "|" + a["rule"], b["page"] + "|" + b["rule"]]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            findings.append(
                {
                    "kind": kind,
                    "a": {"page": a["page"], "rule": a["rule"]},
                    "b": {"page": b["page"], "rule": b["rule"]},
                }
            )
    findings.sort(key=lambda f: (f["kind"], f["a"]["page"], f["b"]["page"]))
    return findings


# ── 分级处置 ─────────────────────────────────────────────────────────────


def _apply_mechanical(
    project_root: Path, scan: dict
) -> tuple[list[str], list[str], set[str], dict[str, int]]:
    """执行机械自修（悬空溯源行/越界 sources、格式、ADR index 状态对齐），
    返回 ``(修复明细, 待人工明细, 实际改写页 relpath 集合, 分类修复计数)``：
    前者只收确实完成改写的条目（修复明细与提交摘要的共同依据），槽位定位
    失败等无法机械处置的场景
    入后者转待人工；relpath 集合只收盘上发生实际改写的文件（仅 sources 全悬空
    保留原值转待人工、无其他改写的页不在其中；混合场景删行页在内，悬空
    sources 保留原值部分另行转待人工），供「本批已纠偏页」判定使用；分类计数
    按 dangling/format/adr 键统计各类修复条数（提交摘要直接消费，不对明细
    文案做子串匹配，文案措辞变更不再导致摘要错计）。
    只写 spec/knowledge/ 内文件。"""
    archives = _existing_archives(project_root)
    fixed: list[str] = []
    manual: list[str] = []
    rewritten: set[str] = set()
    cats = {"dangling": 0, "format": 0, "adr": 0}
    # [fenix-ignore:9c26e33a4a68] 病灶快照已在 run_audit 蒸馏锁内采集，扫描与删行同临界区，并发蒸馏 run 无法在两者之间插写错位行号。
    for item in scan["dangling"]:
        # 页文件在扫描快照后被外部删除/权限变化（锁外人工与 git 操作不受蒸馏
        # 锁约束）时 read_text 抛 OSError 穿出 run_audit，整轮体检中止、日戳不
        # 落盘、后续每个检查点重复失败。读不到按「盘面已变、转待人工」计入
        # manual 明细，不中断本轮机械修复与其余页面处置（对齐 _page_text_by_rel
        # 的 is_file 防护口径）。
        orig_text: Optional[str] = None
        if item["path"].is_file():
            try:
                orig_text = item["path"].read_text(encoding="utf-8", errors="replace")
            except OSError:
                orig_text = None
        if orig_text is None:
            manual.append(
                f"{item['rel']}：盘面已变（文件不可读或已删除），悬空溯源转待人工"
            )
            continue
        lines = orig_text.splitlines()
        drop = set(item["drop_lines"])
        kept = [ln for i, ln in enumerate(lines) if i not in drop]
        text = "\n".join(kept)
        if text and not text.endswith("\n"):
            text += "\n"

        removed_sources = 0

        def _clean_sources(mm: re.Match) -> str:
            nonlocal removed_sources
            fields = mm.group(1)
            sm = re.search(r"sources=([^\s]+)", fields)
            if not sm:
                return mm.group(0)
            names = [s for s in re.split(r"[,，]", sm.group(1)) if s]
            kept_names = [s for s in names if _source_base(s) in archives]
            if not kept_names:
                # sources 全悬空时保留原值不剔除：清空会产出 ``sources=`` 空值，
                # marker 字段正则要求非空，校验将报「marker 字段非法」——该字符
                # 串不在修复前违规快照里，属本轮新违规，会令整轮机械自修被回滚；
                # 保留原值时悬空 sources 违规已在对基快照里，不会拦截提交。
                return mm.group(0)
            removed = len(names) - len(kept_names)
            if not removed:
                # 无剔除时原样返回：marker 契约允许跨行/空白排版差异（_MARKER_RE
                # \s* 宽松前缀 + DOTALL），重建单行规范形态会把仅排版差异当改写，
                # 触发写盘并产出「删除悬空溯源 0 行」的误导计数。
                return mm.group(0)
            removed_sources += removed
            new_fields = fields[: sm.start(1)] + ",".join(kept_names) + fields[sm.end(1) :]
            return f"<!-- knowledge: {new_fields}-->"

        text = _MARKER_RE.sub(_clean_sources, text)
        all_dangling_msg = (
            f"{item['rel']}：marker sources 全部悬空（{len(item['missing_sources'])} 项），"
            f"保留原值待人工处置"
        )
        if text == orig_text:
            # sources 全悬空保留原值且无悬空引用行可删：无实际改写，不写盘、
            # 不计修复明细，转待人工（补建归档目录或人工清理 sources）。
            manual.append(all_dangling_msg)
            continue
        atomic_write_text(item["path"], text)
        rewritten.add(item["rel"])
        fixed.append(
            f"{item['rel']}：删除悬空溯源 {len(drop)} 行"
            + (f"、剔除越界 sources {removed_sources} 项" if removed_sources else "")
        )
        cats["dangling"] += 1
        if removed_sources == 0 and item["missing_sources"]:
            # 混合场景（悬空引用行已删 + sources 全悬空保留原值）：上面 fixed
            # 只计删行，被保留的悬空 sources 当轮无留痕；missing_sources 非空
            # 且 removed_sources == 0 即 kept_names 为空（全悬空未被剔除），
            # 与上方 text == orig_text 分支同文案当轮即转待人工，不等下一轮
            # 体检（删行后 text 不再变化）才补出。
            manual.append(all_dangling_msg)
    for rel in scan["format"]:
        path = Path(project_root) / rel
        # 同悬空段口径：扫描后盘面已变（文件不可读/已删除）时转待人工，
        # 不让 OSError 中断本轮机械修复（code-review 00f39dd6903d）。
        text: Optional[str] = None
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = None
        if text is None:
            manual.append(f"{rel}：盘面已变（文件不可读或已删除），格式清理转待人工")
            continue
        # 只剥脏行尾空白，保留恰好两个空格的 Markdown 硬换行（与扫描同口径）
        cleaned = "\n".join(
            ln.rstrip() if _trailing_ws_dirty(ln) else ln for ln in text.splitlines()
        )
        if cleaned and not cleaned.endswith("\n"):
            cleaned += "\n"
        if cleaned != text:
            atomic_write_text(path, cleaned)
            rewritten.add(rel)
            fixed.append(f"{rel}：清理格式（行尾空白/EOF 换行）")
            cats["format"] += 1
    # ADR index 状态对齐（机械）：替换只作用于状态槽位跨度（_adr_status_slot
    # 按同一切列规则重定位），不碰标题/摘要列，大小写一律对齐为规范小写形
    index_path = Path(project_root) / KNOWLEDGE_DIR / "adr" / "index.md"
    mismatches = scan["adr"]["status_mismatch"]
    if mismatches and index_path.is_file():
        lines = index_path.read_text(encoding="utf-8", errors="replace").splitlines()
        wrote = False
        for mm in mismatches:
            ln = lines[mm["line_no"]]
            slot = _adr_status_slot(ln)
            if slot is None:
                # 状态槽位重定位失败（行内容相对扫描快照已变）不盲改，转待人工
                # 而非计入机械修复。
                manual.append(
                    f"adr/index.md：{mm['name']} 状态槽位定位失败，请人工对齐为 {mm['expected']}"
                )
                continue
            if slot[2] != mm["expected"]:
                lines[mm["line_no"]] = ln[: slot[0]] + mm["expected"] + ln[slot[1] :]
                wrote = True
                fixed.append(
                    f"adr/index.md：{mm['name']} ADR 索引状态对齐为 {mm['expected']}"
                )
                cats["adr"] += 1
        if wrote:
            atomic_write_text(index_path, "\n".join(lines) + "\n")
            rewritten.add(f"{KNOWLEDGE_DIR}/adr/index.md")
    return fixed, manual, rewritten, cats


def build_audit_prompt(kind: str, context_a: str, context_b: str) -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8", errors="replace")
    return (
        text.replace("{{FINDING_KIND}}", kind)
        .replace("{{CONTEXT_A}}", context_a)
        .replace("{{CONTEXT_B}}", context_b)
    )


def _context_block(title: str, page: dict) -> str:
    return f"### {title}：`{page['page']}`\n\n冲突规则行：{page['rule']}\n\n<page>\n{page['text']}\n</page>\n"


def _page_text_by_rel(project_root: Path, rel: str) -> str:
    """按 rel 现读盘上正文。``scan["pages"]`` 的 text 是 run_audit 开头的扫描
    快照，机械自修段可能已删改这些页面（悬空行剔除、格式清理）；转写 prompt
    必须与 LLM 实际要改的盘上内容一致，不得用旧快照拼上下文。"""
    path = Path(project_root) / rel
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


# spec/knowledge/ 未提交改动集合与按 rels 回滚两件工具已收敛为
# knowledge_backfill 单实现（code-review 0f0f5941025c / 36eb21ca1661 /
# 38ce9b967142）：本文件经 import 的 knowledge_dirty_files / discard_paths
# 复用，零改动判定与失败回滚的语义说明见该函数 docstring。

# ── 车道主入口 ───────────────────────────────────────────────────────────


def run_audit(
    project_root,
    logger=None,
    spawn: Optional[Callable] = None,
    config: Optional[dict] = None,
) -> dict:
    """audit 车道入口：扫描五类病灶 → 机械直修提交 / 语义转写 / 报告落盘。

    config 为 ``knowledge.*`` 配置（缺省 None 按 {} 回落缺省值，由
    knowledge_daily_check 挂载点透传）；语义项接入疑点台账
    （.fenix/knowledge_audit_findings.json）：no-conflict 按内容豁免跳派、
    同批快照滞后去重、连续两轮无确定性判定升级待人工。"""
    project_root = Path(project_root)
    log = logger or null_logger()
    cfg = ConfigLoader.get_knowledge_lane_config(config or {})
    core = load_knowledge_core()
    if core is None:
        log.warning(
            "knowledge",
            "audit 车道跳过：core.knowledge 不可用（前置 SPEC add-knowledge-atlas 未合并）",
        )
        return {"triggered": False, "ok": True, "reason": "knowledge-core-unavailable"}
    validate = core.validate_knowledge
    commit = resolve_commit(core)
    spawn = spawn or default_spawn(project_root)

    if not (project_root / KNOWLEDGE_DIR).is_dir():
        return {"triggered": False, "ok": True, "reason": "no-knowledge-dir"}

    counts = {
        "passed": 0,
        "fixed": 0,
        "rewritten": 0,
        "exempt": 0,
        "superseded": 0,
        "pending_manual": 0,
    }
    details: dict[str, object] = {
        "fixed": [],
        "rewritten": [],
        "manual": [],
        "no_conflict": [],
        "exempt": [],
        "superseded": [],
    }

    # 本批已纠偏页集合（2.3）：机械段提交涉及的页 + 语义段转写提交涉及的页。
    # 疑点规则行来自扫描开始快照，涉及页被纠偏后规则行已不代表盘上现状。
    remediated_pages: set[str] = set()

    # ── 机械自修（直修直提交） ──
    # 写段取蒸馏锁：与 DistillManager / run_backfill 共用 .fenix/knowledge-distill.lock
    # flock 单写者——audit 车道（fenixd 主循环挂载，与 DistillManager 同进程）
    # 与归档事件触发的蒸馏 run 并发时，flock 对同进程第二个 fd 同样互斥，本段
    # 的回滚/提交与蒸馏 run 的放弃/提交串行，任一方的 discard 不再清掉对方刚
    # 写入且未提交的产出；写段内不经 DistillManager 任何加锁路径（validate 与
    # 提交工具均无锁），无自阻塞风险。
    with knowledge_distill_lock(project_root):
        # 病灶快照入锁后采集：「决定改什么的读」与「写」必须同处一个互斥区——
        # 扫描在锁外完成时，并发蒸馏 run 持锁重写页面会使 drop_lines / ADR
        # index 行号相对盘上现文错位，机械修复删错行/改错行。语义初筛与体检
        # 报告同以本快照为准（转写前另有 _page_text_by_rel 现读盘上正文兜底）。
        scan = _scan_pages(project_root)
        scan["adr"] = _scan_adrs(project_root)
        semantic_all = _scan_semantic(scan["pages"])

        # 台账提前加载（1.1 解冻点）：escalated 指纹在切片前从候选中剔除——
        # 切片 semantic_all[:MAX_SEMANTIC_RUNS] 已定，循环内 continue 无法让
        # 名额回流到第 11+ 条候选（escalated-skip 占槽会把转写预算锁死在挂起
        # 疑点上，新候选当日零入账）；剔除后 escalated 不再计入转写预算。
        ledger = _load_findings_ledger(project_root)
        escalated = _escalated_entries(ledger)
        escalated_open = bool(escalated)
        escalated_fps = set(escalated)
        # 同指纹候选去重（code-review fa6043ce1992，与 escalated 剔除一趟完成）：
        # _scan_semantic 的 seen_pairs 按「page|原始 rule 文本」拼对去重，同一
        # 规则行在同页出现两次时（A副本1,B）与（A副本2,B）是不同 pair 键、产出
        # 两条候选，但 _finding_fingerprint 输入为（page, 归一化 rule, digits），
        # 两条候选指纹完全相同——不去重则第一条走 fixed 提交后，第二条命中
        # entry.status=="fixed" 重开 suspected 分支再消耗一个名额、再 spawn 一个
        # run 重复复核同一矛盾。同指纹只保留首条（发现顺序不变，豁免路径因哈希
        # 未变不受影响），名额消耗语义对正常单条路径完全不变。
        semantic_pending: list[dict] = []
        seen_candidate_fps: set[str] = set()
        for f in semantic_all:
            fp = _finding_fingerprint(f)
            if fp in escalated_fps or fp in seen_candidate_fps:
                continue
            seen_candidate_fps.add(fp)
            semantic_pending.append(f)

        # 语义初筛候选消费序 = semantic_pending；单轮转写名额（MAX_SEMANTIC_RUNS）
        # 由语义循环按实际派发 run 数消耗（游标/名额见语义循环处注释），此处
        # 不再预切片——原「[:MAX_SEMANTIC_RUNS] 截断 + 循环前留痕」下，exempt
        # （内容未变豁免）条目白占名额（循环内哈希比对后 continue 不 spawn
        # run），豁免条目一多新候选当日零入账，与 escalated 占槽同构。
        semantic_quota = MAX_SEMANTIC_RUNS
        semantic_cursor = 0

        # escalated 报告留痕（1.1/1.2）：移出循环、明细折叠为单条聚合汇总
        # （条数 + 最长龄期，_render_report 专节渲染），不再逐条展开堆积。
        if escalated:
            counts["pending_manual"] += 1
            details["escalated_summary"] = _escalated_summary(escalated)

        # 修复前违规快照：提交闸门只否决「本轮修复新引入的违规」。机械项只修
        # 悬空溯源/格式/ADR index 三类，真相源里脚本修不了的既有违规（marker
        # 缺失等报告项、kebab 名、链接失配、ADR 正文改写……）若一并否决，单个
        # 报告类病灶就会令整轮机械修复被回滚、机械车道被单点病灶长期空转——
        # 修复前后违规清单取差集，既有违规不拦提交，仍走各自报告/待人工路径。
        before_violations = {str(v) for v in (validate(project_root) or [])}
        # carryover：机械段开始前 spec/knowledge/ 已有的未提交改动（上一轮提交
        # 失败 fail-open 留盘的已验证产出、人工在盘上的编辑）。回滚纪律与语义
        # 段同款：只还原本轮触达的文件，不得全目录连带清除。
        carryover = knowledge_dirty_files(project_root)
        fixed, manual_fixes, rewritten_rels, fix_cats = _apply_mechanical(
            project_root, scan
        )
        if manual_fixes:
            counts["pending_manual"] += len(manual_fixes)
            details["manual"].extend(manual_fixes)
        if fixed:
            _, violations = validate_with_repair(
                project_root,
                validate,
                spawn,
                "",
                f"ka-fix-{int(time.time())}",
                repair_rounds=0,  # 机械自修无 run 语境：只验不改（显式声明）
            )
            new_violations = [v for v in violations if str(v) not in before_violations]
            if not new_violations:
                summary = (
                    f"悬空溯源 {fix_cats['dangling']} 处"
                    f"/格式 {fix_cats['format']} 页"
                    f"/ADR 索引 {fix_cats['adr']} 项"
                )
                try:
                    commit(
                        project_root,
                        [KNOWLEDGE_DIR],
                        f"[fenix] knowledge: audit fix {summary}",
                    )
                except Exception as e:  # noqa: BLE001 - 提交失败 fail-open（内容已在盘上）
                    log.warning("knowledge", f"audit 机械修复提交失败（fail-open）：{e}")
                # 机械修复已落盘（提交失败 fail-open 时内容同样在盘上）。
                # 只收实际发生盘上改写的页：sources 全悬空保留原值转待人工的页
                # 盘上未变、快照仍代表现状，其疑点照常复核，不得误标「本批已纠偏」。
                remediated_pages |= rewritten_rels
                counts["fixed"] = len(fixed)
                details["fixed"] = fixed
            else:
                # 只回滚本轮机械修复触达的文件；carryover 在场改动不属本轮产出。
                # 本轮若恰好也改写了 carryover 在场文件则无法拆分，该文件保持在
                # 盘（转写段收尾 leftover 告警与 ADR 目录未提交改动报告可见），
                # 交由下一轮体检或人工处置，不连带销毁既有未提交内容。
                discard_paths(
                    project_root,
                    sorted(knowledge_dirty_files(project_root) - carryover),
                )
                counts["pending_manual"] += 1
                details["manual"].append(
                    f"机械修复引入新违规，已回滚：{new_violations[:3]}"
                )

    # ── 语义转写（矛盾/重复 → 定向蒸馏 run；疑点台账接入豁免/去重/升级） ──
    # escalated 条目已在切片前剔除（1.1）：不进本循环、不占转写预算，也不再
    # 需要循环内 skip 分支；其留痕由循环前聚合汇总统一渲染。
    # 转写名额（MAX_SEMANTIC_RUNS＝单轮转写 run 数上限）按实际派发 run 数
    # 消耗：superseded-in-batch / exempt（内容未变豁免）两条 continue 出口
    # 不 spawn run、不占额，名额自动回流给后续候选；豁免判定（两页哈希比对）
    # 仍在循环内进行——切片点在机械段之前，提前剔除会拿到纠偏前的滞后哈希、
    # 还会丢掉涉及页已纠偏时的 superseded-in-batch 分类。名额耗尽即停，剩余
    # 候选由循环后的截断留痕转入待人工明细。
    idx = 0
    while semantic_cursor < len(semantic_pending) and semantic_quota > 0:
        finding = semantic_pending[semantic_cursor]
        semantic_cursor += 1
        idx += 1
        fp = _finding_fingerprint(finding)
        entry = ledger.get(fp)
        if entry is None:
            entry = _new_finding_entry(finding)
            ledger[fp] = entry
            _save_findings_ledger(project_root, ledger, own_fingerprints={fp})
        pages = [finding["a"]["page"], finding["b"]["page"]]

        # 同批快照滞后去重（2.3）：疑点清单在扫描开始一次性快照，涉及页在本批
        # 已被纠偏（机械段提交或此前转写提交，含 fail-open 落盘）时，快照规则
        # 行已不代表盘上现状，复核是白跑——标记 superseded-in-batch 跳过。
        if pages[0] in remediated_pages or pages[1] in remediated_pages:
            entry["status"] = "superseded-in-batch"
            entry["updated_at"] = _today()
            _save_findings_ledger(project_root, ledger, own_fingerprints={fp})
            counts["superseded"] += 1
            details["superseded"].append(
                f"{finding['kind']}（{pages[0]} × {pages[1]}）：涉及页本批已纠偏，跳过"
            )
            continue

        # no-conflict 按内容豁免（2.1）：两页全文 sha256 均未变才跳派；任一页
        # 变化即解冻回 suspected 照常派发，升级轮次同步清零（豁免解冻重派不计
        # 入升级轮次——每次内容变更重置，翻转情形保有再审价值）。
        if cfg["no_conflict_exempt"] and entry.get("status") == "exempt":
            cur_hashes = {
                rel: _page_hash(project_root, rel) for rel in dict.fromkeys(pages)
            }
            if all(
                entry.get("page_hashes", {}).get(rel) == h for rel, h in cur_hashes.items()
            ):
                entry["exempted_at"] = _today()
                entry["updated_at"] = entry["exempted_at"]
                _save_findings_ledger(project_root, ledger, own_fingerprints={fp})
                counts["exempt"] += 1
                details["exempt"].append(
                    f"{finding['kind']}（{pages[0]} × {pages[1]}）：两页内容未变，豁免复核"
                )
                continue
            entry["status"] = "suspected"
            entry["review_rounds"] = 0
            entry["updated_at"] = _today()
            _save_findings_ledger(project_root, ledger, own_fingerprints={fp})
        elif entry.get("status") in ("fixed", "superseded-in-batch"):
            # 存量已纠偏/已跳过条目再次被扫出：真相源仍有该疑点，重开复核
            entry["status"] = "suspected"
            entry["updated_at"] = _today()
            _save_findings_ledger(project_root, ledger, own_fingerprints={fp})

        # 进入复核：升级轮次 +1（连续 N 轮无确定性判定即升级，N 见配置）。
        # review_rounds 人工编辑/旧版本可能写坏为非数字：就地归零重计走正常
        # 复核并 WARNING 留痕，不让单条损坏条目炸整轮 audit 车道（与
        # _record_verdict 对 verdicts 的就地补齐同口径）。
        raw_rounds = entry.get("review_rounds")
        try:
            prev_rounds = int(raw_rounds or 0)
        except (TypeError, ValueError):
            prev_rounds = 0
            log.warning(
                "knowledge",
                f"audit 台账条目 review_rounds 类型损坏（{raw_rounds!r}），"
                f"就地归零重计：{finding['kind']}"
                f"（{pages[0]} × {pages[1]}）",
            )
        entry["review_rounds"] = prev_rounds + 1

        # 走到此处必然派发一个转写 run（superseded/豁免两条无 run 出口已在
        # 上方 continue），在此消耗转写名额；失败 run 同样计额（run 已 spawn）。
        semantic_quota -= 1
        # 写段取蒸馏锁（同机械段）：每次转写迭代的 spawn→validate→提交/回滚
        # 整体与 DistillManager / run_backfill 串行（与 run_backfill 批次同款
        # 粒度），转写产出在提交前不再可能被并发蒸馏 run 的 discard 清掉。
        with knowledge_distill_lock(project_root):
            run_id = f"ka-rewrite{idx}-{int(time.time())}"
            # 提交/回滚纪律以 spec/knowledge/ 的 git dirty 状态为唯一依据；
            # carryover 是本轮开始前已存在的未提交改动（如机械段提交失败遗留的
            # 已验证产出），失败回滚只作用于本轮新触达的文件。
            carryover = knowledge_dirty_files(project_root)
            # 违规基线进锁后、spawn 前采集（与机械段 before_violations 同款口径）：
            # 失败回滚只在「相对本基线的新发违规」时才连带回滚 carryover，真相源
            # 里与 carryover 无关的既有违规（marker 缺失等报告类病灶）不拦。
            before_violations = {str(v) for v in (validate(project_root) or [])}
            try:
                # prompt 构建纳入同一 try（code-review 52c1a762cce9）：audit.md
                # 缺失/混入非 UTF-8 字节、涉事页在 is_file 检查后被删除或权限
                # 变化（read_text 抛 OSError）都会在此抛异常——位于 try 块之外
                # 会穿出循环与 run_audit，整轮体检中止、日戳不落盘，当日每个
                # 检查点重跑重报；纳入后按既有转写失败路径单点隔离。
                prompt = build_audit_prompt(
                    finding["kind"],
                    _context_block("页面甲", {
                        "page": finding["a"]["page"],
                        "rule": finding["a"]["rule"],
                        "text": _page_text_by_rel(project_root, finding["a"]["page"]),
                    }),
                    _context_block("页面乙", {
                        "page": finding["b"]["page"],
                        "rule": finding["b"]["rule"],
                        "text": _page_text_by_rel(project_root, finding["b"]["page"]),
                    }),
                )
                spawn(prompt, run_id)
                # 透传进锁后采集的违规基线（与 backfill 批次同款差集口径）：修正
                # 反馈与最终否决只看本轮新引入的违规——真相源既有的报告类病灶
                # （超 150 行硬顶页、marker 缺失等）不令转写 run 恒判失败空转、
                # 误回滚有效重写并推高 review_rounds 误升级。
                ok, violations = validate_with_repair(
                    project_root,
                    validate,
                    spawn,
                    prompt,
                    run_id,
                    before_violations=before_violations,
                )
            except Exception as e:  # noqa: BLE001 - 单个转写失败不阻塞其余
                ok, violations = False, [f"转写 run 失败：{e}"]
            dirty_now = knowledge_dirty_files(project_root)
            # 本 run 新触达的文件（2.3 快照滞后去重的「已纠偏」判定基准）：carryover
            # 是本轮开始前已存在的未提交改动，不是本 run 的产出，既不能当作该疑点的
            # 「重写」证据，也不能据此把涉及页标记为本批已纠偏。
            touched = dirty_now - carryover
            if not ok:
                # 只回滚本轮触达的文件，不连带 carryover；本轮若改到 carryover
                # 在场文件则无法拆分——清掉本轮文件后仍存在「相对进锁前基线的
                # 新发违规」时才整体回滚（与机械段修复前后违规清单取差集同款
                # 口径：与 carryover 无关的既有违规不拦——carryover 里的机械产出
                # 下一轮体检可重建，人工在盘上的编辑不可重建，不得因既有违规
                # 被连带销毁）。
                discard_paths(project_root, sorted(touched))
                new_violations = {
                    str(v) for v in (validate(project_root) or [])
                } - before_violations
                if dirty_now & carryover and new_violations:
                    discard_paths(project_root, sorted(dirty_now & carryover))
                counts["pending_manual"] += 1
                if entry["review_rounds"] >= cfg["escalate_after_rounds"]:
                    # 连续两轮进入复核均未产出确定性判定（仍 suspected，如转写
                    # 失败回滚）→ 升级待人工：停止自动复核。todo.md 登记收敛
                    # 为循环后单条聚合行（1.3），此处只留本 run 升级事件明细。
                    entry["status"] = "escalated"
                    entry["updated_at"] = _today()
                    _save_findings_ledger(project_root, ledger, own_fingerprints={fp})
                    details["manual"].append(
                        f"{finding['kind']}（{pages[0]} × {pages[1]}）：连续 "
                        f"{entry['review_rounds']} 轮复核无确定性判定，升级待人工（escalated）"
                    )
                    continue
                details["manual"].append(
                    f"{finding['kind']} 转写失败（{finding['a']['page']} × {finding['b']['page']}）："
                    f"{violations[:2]}，已登记 todo.md"
                )
                append_todo_line(
                    project_root,
                    f"audit 语义项转写失败：{finding['kind']}"
                    f"（{finding['a']['page']} × {finding['b']['page']}），请人工核查",
                )
                _save_findings_ledger(project_root, ledger, own_fingerprints={fp})  # 升级轮次入账
                continue
            if not touched:
                # 「判无矛盾」零改动收场：以本 run 新触达为准——转写 run 把修正落
                # 到涉事两页之外的第三页同样计入 touched 并被下方提交收编，不会滞留
                # 工作区被误判为零改动；carryover 在场改动不是本 run 的判定产出，
                # 不收编进本笔提交（留待其余疑点的 run 或收尾 leftover 曝光）。
                counts["passed"] += 1
                details["no_conflict"].append(
                    f"{finding['kind']}（{finding['a']['page']} × {finding['b']['page']}）：判无矛盾"
                )
                # 判定入账（2.2）：记两页全文哈希作下次初筛的内容豁免键
                _record_verdict(
                    entry,
                    "no-conflict",
                    page_hashes={
                        rel: _page_hash(project_root, rel) for rel in dict.fromkeys(pages)
                    },
                )
                _save_findings_ledger(project_root, ledger, own_fingerprints={fp})
                continue
            summary = f"{finding['kind']} {finding['a']['page']} × {finding['b']['page']}"
            commit_msg = f"[fenix] knowledge: audit rewrite {summary}"
            # pathspec 收窄为本 run 实际触达的文件（code-review 5e5e4ea03d8c）：
            # touched ⊆ spec/knowledge/（knowledge_dirty_files 只扫该目录），整目录
            # pathspec 会把进锁前已在场的 carryover（前序 fail-open 留盘产出、人工
            # 未提交编辑）一并扫进「audit rewrite」提交，与上方「不收编进本笔提交」
            # 的注释承诺矛盾；carryover 留工作区由收尾 leftover 曝光、后续 pathspec
            # 提交自然扫入（与 backfill 车道同口径）。
            try:
                commit(project_root, sorted(touched), commit_msg)
            except Exception as e:  # noqa: BLE001
                log.warning("knowledge", f"audit 转写提交失败（fail-open）：{e}")
            counts["rewritten"] += 1
            details["rewritten"].append(summary)
            # 判定入账（2.2）：重写提交记 fixed；本 run 触达的页快照规则行已滞后，
            # 后续涉及同页的疑点走快照滞后去重（按实际触达而非疑点对全页标记——
            # 未被改动的另一页快照仍有效，其疑点照常复核）
            _record_verdict(entry, "fixed", commit=commit_msg)
            _save_findings_ledger(project_root, ledger, own_fingerprints={fp})
            remediated_pages |= touched

    # 语义初筛截断显式留痕（名额耗尽出口）：未被本轮消费的候选不静默丢弃，
    # 转入待人工明细（报告呈现为「共 N 条、转写名额已用尽、其余人工核查」），
    # 体检报告不再对被截断的矛盾/重复候选呈现为「无更多语义发现」。
    semantic_overflow = semantic_pending[semantic_cursor:]
    if semantic_overflow:
        counts["pending_manual"] += 1
        details["manual"].append(
            f"语义初筛候选共 {len(semantic_pending)} 条，本轮转写名额 "
            f"{MAX_SEMANTIC_RUNS} 个已用尽（豁免/已纠偏疑点不占额），"
            f"其余 {len(semantic_overflow)} 条请人工核查"
        )

    # escalated 视图收尾渲染前从盘上台账重读（对齐语义循环回写的己方指纹键
    # 口径）：循环内每次回写只落本方指纹键，盘上台账已是此刻权威视图——开局
    # 快照里的 escalated 条目可能在循环期间（最多 MAX_SEMANTIC_RUNS 个转写
    # run）被 consume_arbitration 消费删除（dashboard --serve / 300s 检查点），
    # 若仍以开局快照渲染 todo 聚合行、disputed 注记与报告汇总，已消费条目会
    # 以待仲裁形态复活，人工仲裁决定被静默作废。本轮循环内新升级的条目升级
    # 时已按己方键落盘，重读自然计入。
    escalated = _escalated_entries(_load_findings_ledger(project_root))

    # 升级登记聚合行（1.3）：循环后写一次，同前缀替换不追加（龄期逐日推进由
    # upsert 整行替换消化，聚合行不变成每日重述）；历史逐条行（旧前缀）一并
    # 清理；台账 escalated 清零（仲裁消费/人工删条目）时按纯清理语义摘除残留。
    upsert_todo_line(
        project_root,
        TODO_ESCALATED_AGG_PREFIX,
        _escalated_todo_line(escalated),
        cleanup_prefixes=(TODO_ESCALATED_LEGACY_PREFIX,),
    )

    # 超龄注记（2.1）：escalated 超过阈值天数 → 涉事页顶 disputed 注记（机器
    # 可读 HTML 注释、不含 knowledge: 前缀、不引用 archive 路径、写前查 150
    # 行硬顶）。写盘与提交同取蒸馏锁（同机械段/转写段/仲裁消费段口径），写完
    # 走既有 [fenix] knowledge 提交路径自提交——框架自己的注记改动不留工作区，
    # 避免成为下一轮 audit 的 dirty carryover 告警源。
    stale_days = cfg["escalated_stale_days"]
    desired = _disputed_targets(escalated, stale_days)
    annotated = {p["rel"] for p in scan["pages"] if _DISPUTED_RE.search(p["text"])}
    with knowledge_distill_lock(project_root):
        changed, note_skipped = _sync_disputed_annotations(
            project_root, desired, restrict_pages=set(desired) | annotated
        )
        # 提交留在临界区内：锁外提交的窗口期里，并发蒸馏 run 会把刚落盘未提交
        # 的注记当 carryover，其全目录 pathspec 提交还会把注记卷进蒸馏提交
        # （污染提交归属），或与注记提交撞 git index.lock 走 fail-open 告警。
        if changed:
            try:
                commit(
                    project_root,
                    [KNOWLEDGE_DIR],
                    f"[fenix] knowledge: audit disputed 注记同步（{len(changed)} 页）",
                )
            except Exception as e:  # noqa: BLE001 - 提交失败 fail-open（内容已在盘上）
                log.warning("knowledge", f"disputed 注记提交失败（fail-open）：{e}")
    if note_skipped:
        counts["pending_manual"] += 1
        details["manual"].append(
            f"disputed 注记写入跳过（页超 {LINE_CAP} 行硬顶）：{'、'.join(note_skipped)}"
        )

    leftover = knowledge_dirty_files(project_root)
    if leftover:
        # 转写段结束仍有未提交改动（提交失败 fail-open 的已验证产出）显式
        # 曝光，留待后续提交扫入或人工处置，不再无声滞留工作区。
        log.warning(
            "knowledge",
            f"audit 转写段结束仍有未提交改动（多为已验证产出，留待后续提交或人工处置）："
            f"{sorted(leftover)[:5]}",
        )

    # ── 报告项与规模趋势 ──
    manual_items = (
        [f"{item['rel']}：超 {LINE_CAP} 行硬顶（{item['lines']} 行）" for item in scan["overcap"]]
        + list(scan["dangling_suspect"])
        + [f"{rel}：能力页 marker 缺失或不可解析" for rel in scan["no_marker"]]
        + [f"ADR supersede 链断裂：{item}" for item in scan["adr"]["broken_chain"]]
        + (
            [f"ADR 目录存在未提交改动：{len(scan['adr']['adr_dirty'])} 项"]
            if scan["adr"]["adr_dirty"]
            else []
        )
    )
    counts["pending_manual"] += len(manual_items)
    details["manual"] = details["manual"] + manual_items
    # 干净类别计入「过」
    clean_classes = sum(
        1
        for v in (
            scan["dangling"],
            scan["dangling_suspect"],
            scan["overcap"],
            scan["format"],
            scan["no_marker"],
            scan["adr"]["broken_chain"],
            semantic_pending,
        )
        if not v
    )
    counts["passed"] += clean_classes

    scale = scale_stats(project_root)
    state = _read_state(project_root)
    last_scale = state.get("last_scale") or {}
    prev_lines = last_scale.get("lines") or 0
    growth = (
        (scale["lines"] - prev_lines) / prev_lines if prev_lines > 0 else 0.0
    )
    slim = growth > GROWTH_FLAG_RATIO
    # 候选清单统一来源：≥ LINE_CAP//2 行的页按行数降序取前列 10（供下一轮
    # 蒸馏/audit 处置），slim 与否只影响「需精简」结论。此前 slim 分支仅取
    # 超 150 行硬顶页——总行数增长达标但无超限页时清单为空、人工无从下手，
    # 且与 not slim 分支（≥半硬顶取前列）口径不一致。
    page_lines = []
    for page in scan["pages"]:
        n = len(page["text"].splitlines())
        if n >= LINE_CAP // 2:
            page_lines.append({"rel": page["rel"], "lines": n})
    slim_candidates = sorted(page_lines, key=lambda x: -x["lines"])[:10]

    # escalated 汇总渲染前重算（code-review 373cc9019334 / 1e00c2c85434）：
    # details["escalated_summary"] 在语义循环前由当时台账快照定格，循环内新升级
    # 的条目（已随收尾前的盘上重读计入 escalated）此前只进 todo 聚合行与
    # disputed 注记——报告汇总少计本轮新升级条目，报告/todo/注记三个出口口径
    # 不一致。用最终 escalated 重算覆盖（escalated 为空时 _escalated_summary
    # 返回 None，汇总节照旧不出）。
    details["escalated_summary"] = _escalated_summary(escalated)
    if escalated_open and not escalated:
        # 开局 escalated 非空时 pending_manual 已 +1；收尾按盘上重读的最终
        # escalated 重算汇总后若已清空（循环期间被外部消费者消费/删除），回撤
        # 该笔幻影计数，与汇总节「共 0 条待人工仲裁」口径对齐（code-review
        # 2d4029f87294）。
        counts["pending_manual"] -= 1

    report = _render_report(
        counts,
        details,
        scale,
        prev_lines,
        growth,
        slim,
        slim_candidates,
        escalated_summary=details.get("escalated_summary"),
    )
    atomic_write_text(project_root / REPORT_RELPATH, report)
    # 收尾回写持 _state_write_lock 重读盘上状态再只写 last_scale：体检期读下
    # 的开局快照到收尾之间，另一进程的消费段/日戳回写可能已落盘其他键，直接
    # 回写陈旧快照会整体覆盖（仲裁留痕丢失、当日日戳丢失致体检重复跑）。
    with _state_write_lock(project_root):
        state = _read_state(project_root)
        state["last_scale"] = scale
        _write_state(project_root, state)
    log.info(
        "knowledge",
        f"audit 体检完成：修 {counts['fixed']} / 转写 {counts['rewritten']} / "
        f"豁免 {counts.get('exempt', 0)} / 待人工 {counts['pending_manual']} / "
        f"过 {counts['passed']}"
        + ("（需精简）" if slim else ""),
    )
    return {
        "triggered": True,
        "ok": True,
        "counts": counts,
        "slim_flag": slim,
        "growth": round(growth, 4),
        "scale": scale,
    }


def _render_report(
    counts: dict,
    details: dict,
    scale: dict,
    prev_lines: int,
    growth: float,
    slim: bool,
    slim_candidates: list,
    escalated_summary: Optional[dict] = None,
) -> str:
    lines = [
        "# 知识真相源 audit 体检报告",
        "",
        f"- 体检时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        "- 结论：**需精简**" if slim else "- 结论：通过",
        f"- 计数：过 {counts['passed']} / 修 {counts['fixed']} / "
        f"转写 {counts['rewritten']} / 豁免 {counts.get('exempt', 0)} / "
        f"待人工 {counts['pending_manual']}",
        f"- 规模：{scale.get('domains', 0)} 域 / {scale.get('pages', 0)} 能力页 / "
        f"{scale.get('adrs', 0)} ADR / {scale.get('lines', 0)} 行"
        + (
            f"（上次 {prev_lines} 行，变化 {growth:+.0%}）" if prev_lines else ""
        ),
        "",
    ]
    if slim:
        lines.append("## 需精简：规模增长超 +10%")
        lines.append("")
        lines.append("候选页清单（按行数降序，供下一轮蒸馏/audit 处置）：")
        lines.append("")
        for cand in slim_candidates:
            lines.append(f"- `{cand['rel']}`（{cand['lines']} 行）")
        lines.append("")
    # escalated 明细折叠为单条聚合汇总（1.2）：条数 + 最长龄期，不逐条展开
    if escalated_summary:
        lines.append("## 升级待人工（escalated）汇总")
        lines.append("")
        lines.append(
            f"- 共 {escalated_summary['count']} 条待人工仲裁，最长龄期 "
            f"{escalated_summary['max_age_days']} 天（自 first_seen 起算）"
        )
        lines.append(
            f"- 仲裁入口：`{ARBITRATION_RELPATH}`"
            f"（登记 fingerprint/decision/decided_at/note，框架检查点自动消费）"
        )
        lines.append("")
    for title, key in (
        ("机械自修明细", "fixed"),
        ("转写明细", "rewritten"),
        ("判无矛盾（初筛误报）", "no_conflict"),
        ("内容未变豁免（台账命中）", "exempt"),
        ("本批跳过（快照滞后重复）", "superseded"),
        ("待人工明细", "manual"),
    ):
        if details.get(key):
            lines.append(f"## {title}")
            lines.append("")
            lines.extend(f"- {item}" for item in details[key])
            lines.append("")
    return "\n".join(lines)


# ── Graphify 关系图生成（D3）——已随功能取消整段下线（2026-09-29）─────────
