"""周期 audit 淘汰车道 + Graphify 关系图生成（add-knowledge-atlas-maintenance D2/D3）。

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

Graphify 关系图与 audit 共用每日检查点（D3：一个自然日检查点先后跑 audit 与
graph，减少唤醒）：``shutil.which('graphify')`` 探测，缺失/执行失败 fail-open
单行日志跳过，产物 pathspec 限定提交 ``spec/knowledge/graph/``。

挂载：``fenixd.py`` 主循环 300s 周期检查点调 ``knowledge_daily_check``（与自动
归档同款挂载）；门控 ``knowledge.audit_enabled`` / ``knowledge.graph_enabled``
（core/config.py get_knowledge_lane_config，缺省 True）。
"""

from __future__ import annotations

import difflib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from core.config import ConfigLoader
from core.knowledge_backfill import (
    _NullLogger,
    _validate_with_repair,
    append_todo_line,
    atomic_write_text,
    commit_pathspec,
    default_spawn,
    discard_knowledge_changes,
    load_knowledge_core,
    resolve_commit,
    scale_stats,
)

# ── 常量 ─────────────────────────────────────────────────────────────────

REPORT_RELPATH = ".fenix/knowledge_audit_report.md"
STATE_RELPATH = ".fenix/knowledge_audit_state.json"
PROMPT_PATH = Path(__file__).parent / "knowledge_prompts" / "audit.md"
KNOWLEDGE_DIR = "spec/knowledge"
GRAPH_RELPATH = "spec/knowledge/graph"
GRAPH_ARTIFACTS = ("graph.html", "GRAPH_REPORT.md", "graph.json")

# 单页 150 行硬顶（前置 SPEC 目录契约定稿，本车道只消费）
LINE_CAP = 150
# 规模趋势「需精简」阈值：总行数相对上次体检增长超 +10%
GROWTH_FLAG_RATIO = 0.10
# 语义项单轮转写 run 数上限（误报进 run 由 LLM 终判，但需封顶控成本）
MAX_SEMANTIC_RUNS = 10
# graphify 单次生成硬超时（秒）
GRAPH_TIMEOUT_SECONDS = 1800

_MARKER_RE = re.compile(r"<!--\s*knowledge:\s*(.*?)-->", re.DOTALL)
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


def _today() -> str:
    return time.strftime("%Y-%m-%d")


# ── 每日检查点（fenixd 主循环挂载入口） ──────────────────────────────────


def knowledge_daily_check(
    project_root,
    config: Optional[dict] = None,
    logger=None,
    audit_lane: Optional[Callable] = None,
    graph_lane: Optional[Callable] = None,
) -> dict:
    """daemon 主循环 300s 周期调用的每日检查点（audit → graph 先后跑）。

    门控与防重语义：
    - ``knowledge.audit_enabled`` / ``knowledge.graph_enabled`` 独立门控；
    - 两车道各自按状态文件的自然日戳同自然日防重（只跑一次）；
    - 双双禁用或当日均已跑 → 静默返回，零日志噪音（禁用跳过场景）；
    - 车道抛异常记日志不更新日戳（下一周期重试），不中断主循环（挂载侧同款
      try/except）。
    """
    project_root = Path(project_root)
    log = logger or _NullLogger()
    cfg = ConfigLoader.get_knowledge_lane_config(config or {})
    audit_enabled = cfg["audit_enabled"]
    graph_enabled = cfg["graph_enabled"]
    if not audit_enabled and not graph_enabled:
        return {"triggered": False, "reason": "disabled"}
    state = _read_state(project_root)
    today = _today()
    results: dict[str, dict] = {}

    if audit_enabled and state.get("last_audit_date") != today:
        try:
            lane = audit_lane or run_audit
            res = lane(project_root, logger=log) or {}
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
            state["last_audit_date"] = today
            _write_state(project_root, state)

    if graph_enabled and state.get("last_graph_date") != today:
        try:
            lane = graph_lane or run_graph
            res = lane(project_root, logger=log) or {}
        except Exception as e:  # noqa: BLE001
            log.error("knowledge", f"graph 生成执行失败（下周期重试）：{e}")
            res = {"ok": False, "error": str(e)}
        results["graph"] = res
        # graph 的 fail-open 跳过（CLI 缺失/执行失败）同样落日戳：每周期重试
        # 会把单行日志放大成日志噪音（违背 fail-open 初衷），当日不再重试。
        if "error" not in res:
            state["last_graph_date"] = today
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


def _scan_pages(project_root: Path) -> dict:
    """五类病灶中的页级扫描：悬空溯源（①② 机械）、超行数（报告）、格式。"""
    pages = _collect_pages(project_root)
    archives = _existing_archives(project_root)
    dangling_pages: list[dict] = []  # 机械：页 rel → 待删行/待删 sources
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
            missing_sources = [s for s in names if _source_base(s) not in archives]
        for i, ln in enumerate(lines):
            for m in _ARCHIVE_REF_RE.finditer(ln):
                if m.group(1).strip("\"'`") not in archives:
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
        # 格式违规（机械可修）：行尾空白 / 文件缺结尾换行
        if any(ln != ln.rstrip() for ln in lines) or (
            text and not text.endswith("\n")
        ):
            format_pages.append(page["rel"])
    return {
        "pages": pages,
        "dangling": dangling_pages,
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
            if m and not (adr_dir / f"{m.group(1)}.md").is_file():
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
    规则 → 重复候选。LLM 在转写 run 里终判，误报由「判无矛盾」零改动收场。"""
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
    return findings[:MAX_SEMANTIC_RUNS]


# ── 分级处置 ─────────────────────────────────────────────────────────────


def _apply_mechanical(project_root: Path, scan: dict) -> list[str]:
    """执行机械自修（悬空溯源行/越界 sources、格式、ADR index 状态对齐），
    返回修复摘要明细。只写 spec/knowledge/ 内文件。"""
    archives = _existing_archives(project_root)
    fixed: list[str] = []
    for item in scan["dangling"]:
        text = item["path"].read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        drop = set(item["drop_lines"])
        kept = [ln for i, ln in enumerate(lines) if i not in drop]
        text = "\n".join(kept)
        if text and not text.endswith("\n"):
            text += "\n"

        def _clean_sources(mm: re.Match) -> str:
            fields = mm.group(1)
            sm = re.search(r"sources=([^\s]+)", fields)
            if not sm:
                return mm.group(0)
            names = [s for s in re.split(r"[,，]", sm.group(1)) if s]
            kept_names = [s for s in names if _source_base(s) in archives]
            new_fields = fields[: sm.start(1)] + ",".join(kept_names) + fields[sm.end(1) :]
            return f"<!-- knowledge: {new_fields}-->"

        text = _MARKER_RE.sub(_clean_sources, text)
        atomic_write_text(item["path"], text)
        fixed.append(
            f"{item['rel']}：删除悬空溯源 {len(drop)} 行"
            + (f"、剔除越界 sources {len(item['missing_sources'])} 项" if item["missing_sources"] else "")
        )
    for rel in scan["format"]:
        path = Path(project_root) / rel
        text = path.read_text(encoding="utf-8", errors="replace")
        cleaned = "\n".join(ln.rstrip() for ln in text.splitlines())
        if cleaned and not cleaned.endswith("\n"):
            cleaned += "\n"
        if cleaned != text:
            atomic_write_text(path, cleaned)
            fixed.append(f"{rel}：清理格式（行尾空白/EOF 换行）")
    # ADR index 状态对齐（机械）：替换只作用于状态槽位跨度（_adr_status_slot
    # 按同一切列规则重定位），不碰标题/摘要列，大小写一律对齐为规范小写形
    index_path = Path(project_root) / KNOWLEDGE_DIR / "adr" / "index.md"
    mismatches = scan["adr"]["status_mismatch"]
    if mismatches and index_path.is_file():
        lines = index_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for mm in mismatches:
            ln = lines[mm["line_no"]]
            slot = _adr_status_slot(ln)
            if slot and slot[2] != mm["expected"]:
                lines[mm["line_no"]] = ln[: slot[0]] + mm["expected"] + ln[slot[1] :]
            fixed.append(f"adr/index.md：{mm['name']} 状态对齐为 {mm['expected']}")
        atomic_write_text(index_path, "\n".join(lines) + "\n")
    return fixed


def build_audit_prompt(kind: str, context_a: str, context_b: str) -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8")
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


def _knowledge_dirty_files(project_root: Path) -> set[str]:
    """spec/knowledge/ 内未提交改动的 relpath 集合（tracked 改动 + 未跟踪新增）。

    转写段的零改动判定与提交/回滚范围都以此为唯一依据——只快照涉事两页会
    漏掉转写 run 落在第三页的修正（误判零改动后改动滞留工作区）。git 不可用/
    超时 fail-open 返回空集。"""
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
        rel = ln[3:].strip().strip('"')
        if " -> " in rel:  # 重命名条目取新路径
            rel = rel.split(" -> ", 1)[1]
        if rel:
            files.add(rel)
    return files


def _discard_paths(project_root: Path, rels: list[str]) -> None:
    """只回滚指定文件（tracked restore + 未跟踪 clean），不碰工作区其他改动。

    语义转写失败路径用它在清除本轮半成品的同时保住早前已验证但未提交的
    产出（如机械段提交失败遗留内容），不得全目录连带回滚。"""
    if not rels:
        return
    for cmd in (
        ["git", "restore", "--", *rels],
        ["git", "clean", "-qfd", "--", *rels],
    ):
        try:
            subprocess.run(
                cmd,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


# ── 车道主入口 ───────────────────────────────────────────────────────────


def run_audit(project_root, logger=None, spawn: Optional[Callable] = None) -> dict:
    """audit 车道入口：扫描五类病灶 → 机械直修提交 / 语义转写 / 报告落盘。"""
    project_root = Path(project_root)
    log = logger or _NullLogger()
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

    scan = _scan_pages(project_root)
    scan["adr"] = _scan_adrs(project_root)
    semantic = _scan_semantic(scan["pages"])

    counts = {"passed": 0, "fixed": 0, "rewritten": 0, "pending_manual": 0}
    details: dict[str, list] = {"fixed": [], "rewritten": [], "manual": [], "no_conflict": []}

    # ── 机械自修（直修直提交） ──
    fixed = _apply_mechanical(project_root, scan)
    if fixed:
        ok, violations = _validate_with_repair(
            project_root,
            validate,
            spawn,
            "",
            f"ka-fix-{int(time.time())}",
            repair_rounds=0,  # 机械自修无 run 语境：只验不改（显式声明）
        )
        if ok:
            summary = (
                f"悬空溯源 {sum(1 for f in fixed if '悬空' in f)} 处"
                f"/格式 {sum(1 for f in fixed if '格式' in f)} 页"
                f"/ADR 索引 {sum(1 for f in fixed if '索引' in f)} 项"
            )
            try:
                commit(project_root, [KNOWLEDGE_DIR], f"[fenix] knowledge: audit fix {summary}")
            except Exception as e:  # noqa: BLE001 - 提交失败 fail-open（内容已在盘上）
                log.warning("knowledge", f"audit 机械修复提交失败（fail-open）：{e}")
            counts["fixed"] = len(fixed)
            details["fixed"] = fixed
        else:
            discard_knowledge_changes(project_root)
            counts["pending_manual"] += 1
            details["manual"].append(
                f"机械修复后校验仍违规，已回滚：{violations[:3]}"
            )

    # ── 语义转写（矛盾/重复 → 定向蒸馏 run） ──
    for idx, finding in enumerate(semantic, 1):
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
        run_id = f"ka-rewrite{idx}-{int(time.time())}"
        # 提交/回滚纪律以 spec/knowledge/ 的 git dirty 状态为唯一依据；
        # carryover 是本轮开始前已存在的未提交改动（如机械段提交失败遗留的
        # 已验证产出），失败回滚只作用于本轮新触达的文件。
        carryover = _knowledge_dirty_files(project_root)
        try:
            spawn(prompt, run_id)
            ok, violations = _validate_with_repair(project_root, validate, spawn, prompt, run_id)
        except Exception as e:  # noqa: BLE001 - 单个转写失败不阻塞其余
            ok, violations = False, [f"转写 run 失败：{e}"]
        dirty_now = _knowledge_dirty_files(project_root)
        if not ok:
            # 只回滚本轮触达的文件，不连带 carryover；本轮若改到 carryover
            # 在场文件则无法拆分——清掉本轮文件后仍违规时整体回滚（carryover
            # 里的机械产出是确定性的，下一轮体检会重建）。
            _discard_paths(project_root, sorted(dirty_now - carryover))
            if dirty_now & carryover and [str(v) for v in (validate(project_root) or [])]:
                _discard_paths(project_root, sorted(dirty_now & carryover))
            counts["pending_manual"] += 1
            details["manual"].append(
                f"{finding['kind']} 转写失败（{finding['a']['page']} × {finding['b']['page']}）："
                f"{violations[:2]}，已登记 todo.md"
            )
            append_todo_line(
                project_root,
                f"audit 语义项转写失败：{finding['kind']}"
                f"（{finding['a']['page']} × {finding['b']['page']}），请人工核查",
            )
            continue
        if not dirty_now:
            # 「判无矛盾」零改动收场：dirty 面向整个真相源目录，转写 run 把
            # 修正落到涉事两页之外的第三页同样会被下方提交收编，不会滞留
            # 工作区被误判为零改动。
            counts["passed"] += 1
            details["no_conflict"].append(
                f"{finding['kind']}（{finding['a']['page']} × {finding['b']['page']}）：判无矛盾"
            )
            continue
        summary = f"{finding['kind']} {finding['a']['page']} × {finding['b']['page']}"
        try:
            commit(project_root, [KNOWLEDGE_DIR], f"[fenix] knowledge: audit rewrite {summary}")
        except Exception as e:  # noqa: BLE001
            log.warning("knowledge", f"audit 转写提交失败（fail-open）：{e}")
        counts["rewritten"] += 1
        details["rewritten"].append(summary)

    leftover = _knowledge_dirty_files(project_root)
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
            scan["overcap"],
            scan["format"],
            scan["no_marker"],
            scan["adr"]["broken_chain"],
            semantic,
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
    slim_candidates = [
        {"rel": item["rel"], "lines": item["lines"]}
        for item in sorted(scan["overcap"], key=lambda x: -x["lines"])
    ]
    if not slim:
        # 候选清单：按行数降序前列页（供下一轮蒸馏/audit 处置）
        page_lines = []
        for page in scan["pages"]:
            n = len(page["text"].splitlines())
            if n >= LINE_CAP // 2:
                page_lines.append({"rel": page["rel"], "lines": n})
        slim_candidates = sorted(page_lines, key=lambda x: -x["lines"])[:10]

    report = _render_report(counts, details, scale, prev_lines, growth, slim, slim_candidates)
    atomic_write_text(project_root / REPORT_RELPATH, report)
    state["last_scale"] = scale
    _write_state(project_root, state)
    log.info(
        "knowledge",
        f"audit 体检完成：修 {counts['fixed']} / 转写 {counts['rewritten']} / "
        f"待人工 {counts['pending_manual']} / 过 {counts['passed']}"
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
) -> str:
    lines = [
        "# 知识真相源 audit 体检报告",
        "",
        f"- 体检时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        "- 结论：**需精简**" if slim else "- 结论：通过",
        f"- 计数：过 {counts['passed']} / 修 {counts['fixed']} / "
        f"转写 {counts['rewritten']} / 待人工 {counts['pending_manual']}",
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
    for title, key in (
        ("机械自修明细", "fixed"),
        ("转写明细", "rewritten"),
        ("判无矛盾（初筛误报）", "no_conflict"),
        ("待人工明细", "manual"),
    ):
        if details.get(key):
            lines.append(f"## {title}")
            lines.append("")
            lines.extend(f"- {item}" for item in details[key])
            lines.append("")
    return "\n".join(lines)


# ── Graphify 关系图生成（D3） ────────────────────────────────────────────


def run_graph(
    project_root,
    config: Optional[dict] = None,
    logger=None,
    which: Optional[Callable] = None,
    run_cmd: Optional[Callable] = None,
) -> dict:
    """每日 Graphify 生成：CLI 缺失/执行失败 fail-open 单行日志，产物入库。

    which/run_cmd 为注入缝（单测假 CLI 替身）；config 门控
    ``knowledge.graph_enabled``（false 时静默跳过，既有产物保留可渲染）。
    """
    project_root = Path(project_root)
    log = logger or _NullLogger()
    cfg = ConfigLoader.get_knowledge_lane_config(config or {})
    if not cfg["graph_enabled"]:
        return {"triggered": False, "reason": "disabled"}
    which = which or shutil.which
    cli = which("graphify")
    if not cli:
        # PyPI 包名确为 graphifyy（graphifyy 0.9.70，graphify.com 出品；pypi 上
        # 不存在 graphify 包，名被平台占位），安装后的 CLI 二进制叫 graphify——
        # 与上方 which 探测名一致，安装命令非笔误。面板侧同款安装提示见
        # core/dashboard/static/src/pages/settings/knowledgeSettings.ts
        # knowledgeSwitchDesc("graph")，两处文案须同步。
        log.info(
            "knowledge",
            "graphify 未安装，跳过本次关系图生成（人工安装：uv tool install graphifyy）",
        )
        return {"triggered": False, "reason": "cli-missing"}
    if not (project_root / KNOWLEDGE_DIR).is_dir():
        return {"triggered": False, "reason": "no-knowledge-dir"}
    if run_cmd is None:

        def run_cmd(cmd, timeout):  # noqa: E306 - 生产实现
            return subprocess.run(
                cmd, cwd=str(project_root), capture_output=True, text=True, timeout=timeout
            )

    try:
        proc = run_cmd([cli, KNOWLEDGE_DIR, "--out", GRAPH_RELPATH], GRAPH_TIMEOUT_SECONDS)
    except Exception as e:  # noqa: BLE001 - 执行失败 fail-open
        log.warning("knowledge", f"graphify 执行失败，跳过本次生成：{e}")
        return {"triggered": False, "reason": "cli-failed"}
    returncode = getattr(proc, "returncode", 1)
    if returncode != 0:
        stderr = (getattr(proc, "stderr", "") or "").strip()[-200:]
        log.warning("knowledge", f"graphify 非零退出（{returncode}），跳过本次生成：{stderr}")
        return {"triggered": False, "reason": "cli-failed"}
    missing = [
        name for name in GRAPH_ARTIFACTS if not (project_root / GRAPH_RELPATH / name).is_file()
    ]
    if missing:
        log.warning(
            "knowledge", f"graphify 产物缺失（{', '.join(missing)}），跳过入库"
        )
        return {"triggered": False, "reason": "artifacts-missing"}
    committed = False
    try:
        committed = commit_pathspec(
            project_root, [GRAPH_RELPATH], "[fenix] knowledge: graph update"
        )
    except Exception as e:  # noqa: BLE001 - 提交失败 fail-open
        log.warning("knowledge", f"graph 产物提交失败（fail-open）：{e}")
    log.info("knowledge", f"知识关系图已生成（committed={committed}）：{GRAPH_RELPATH}/")
    return {"triggered": True, "ok": True, "committed": committed}
