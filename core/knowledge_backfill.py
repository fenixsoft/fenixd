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
  pending/distilled/failed，断点独立续跑；v1 归档粒度条目首次重入作废重建；
- 首段「聚类自举 run」：读链索引能力全集，产出域骨架与 ``能力名 → 域`` 归位清单，
  并接入史前复原段（git 考古求差，未覆盖能力产史前页、已覆盖能力基线作链头）；
- 中段按域分批派发聚合蒸馏 run，每批经 ``validate_knowledge`` 全量校验（≤2 轮
  修正反馈）后 pathspec 限定提交；末段 ADR 抽取批次（读归档 design.md）；
- failed 批标 failed 并登记 todo.md，不阻塞后续批；两维度全部终态后收敛，产出
  汇报，车道幂等（收敛后重入零派发）。

依赖：``core.knowledge`` 的 ``validate_knowledge`` 与提交工具函数经延迟导入复用；
前置未合并时车道整体降级为单行日志跳过（fail-open）。回填期 ``core.knowledge``
派发漏斗经 ``ledger_has_pending``/``register_archive_pending`` 排队协作（台账在盘，
``spec/knowledge/`` 回填期只有回填一个写者；本模块顶层不 import ``core.knowledge``，
反向导入不构成环）。

激活方式：一次性批量车道，合并后手工激活（Migration Plan）——
``python3 -m core.knowledge_backfill --project-root <主树>``；daemon 不自动挂载，
避免合并即烧十几个蒸馏 run。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Optional

# spawn 注入缝：run 内单测用 fake spawn 替身；生产用 _default_spawn（claude -p）。
SpawnFn = Callable[[str, str], str]

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
    """整文件原子回写（tmp + os.replace）：裸 write_text 截断重写在进程中途
    被打断会留半截文件（self_review 同款教训），台账/报告/域清单共用。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def append_todo_line(project_root: Path, line: str) -> bool:
    """向项目 ``.fenix/todo.md`` 追加一条待办（幂等：同文本已存在则跳过）。

    归位到今日日期节（``## YYYY-MM-DD``）下的「### 知识真相源」小节；日期节缺失
    时在文件尾部新建。给人看的队列，不进任务门禁（对齐前置 SPEC D3 口径）。
    """
    today = time.strftime("%Y-%m-%d")
    todo_path = Path(project_root) / ".fenix" / "todo.md"
    text = todo_path.read_text(encoding="utf-8") if todo_path.exists() else ""
    if line in text:
        return False
    subsection = "### 知识真相源"
    lines = text.splitlines()
    # 定位今日日期节行号；无则新建于尾部
    today_idx = next((i for i, ln in enumerate(lines) if ln.strip() == f"## {today}"), None)
    if today_idx is None:
        lines += ["", f"## {today}", subsection, f"- {line}"]
    else:
        # 今日节边界 = 下一个 `## ` 日期节或文件尾
        end = next(
            (i for i in range(today_idx + 1, len(lines)) if lines[i].startswith("## ")),
            len(lines),
        )
        block = lines[today_idx:end]
        sub_idx = next((i for i, ln in enumerate(block) if ln.strip() == subsection), None)
        if sub_idx is None:
            lines[today_idx:end] = block + [subsection, f"- {line}"]
        else:
            block.insert(sub_idx + 1, f"- {line}")
            lines[today_idx:end] = block
    atomic_write_text(todo_path, "\n".join(lines).rstrip("\n") + "\n")
    return True


# ── git 工具（pathspec 限定提交，主树直跑） ─────────────────────────────


def _git(project_root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(project_root),
        capture_output=True,
        text=True,
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


def discard_knowledge_changes(project_root: Path) -> None:
    """放弃本次产出：restore 已跟踪文件 + 清理目录内未跟踪新增（不留半成品，
    对齐前置 SPEC 蒸馏放弃语义）。只清 ``spec/knowledge/``，不碰他物。"""
    project_root = Path(project_root)
    kdir = project_root / KNOWLEDGE_DIR
    subprocess.run(
        ["git", "restore", "--", KNOWLEDGE_DIR],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if kdir.is_dir():
        subprocess.run(
            ["git", "clean", "-qfd", "--", KNOWLEDGE_DIR],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=120,
        )


def resolve_commit(core) -> Callable[[Path, list[str], str], bool]:
    """提交工具接线（任务 2.3）：优先复用 core.knowledge 的提交工具函数，
    缺失时回退车道内 pathspec 提交实现（两者均为 pathspec 限定语义）。"""
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


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class BackfillLedger:
    """回填进度台账 v2（``.fenix/knowledge_backfill.jsonl``，双维度条目）。

    条目键带维度前缀：``capability:<能力名>``（能力页聚合蒸馏）与
    ``adr:<归档名>``（该归档 design.md 的 ADR 抽取扫描），各自
    pending/distilled/failed，断点重入按维度独立续跑；收敛汇报分维度计数。
    v1 归档粒度条目（无前缀键）首次重入作废重建——回填尚未真跑过，无迁移
    负担（台账是运行时进度非数据资产，design D2）。
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: dict[str, dict[str, Any]] = {}
        self.legacy_discarded = False

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
        if any(not _is_v2_key(k) for k in ledger.entries):
            ledger.entries = {}
            ledger.legacy_discarded = True
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

    台账在盘、原子回写，重启安全。Returns: 是否发生登记/重置。
    """
    root = Path(project_root)
    ledger = BackfillLedger.load(root / LEDGER_RELPATH)
    specs = root / "spec" / "archive" / archive_name / "specs"
    caps = (
        sorted(p.name for p in specs.iterdir() if p.is_dir())
        if specs.is_dir()
        else []
    )
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


def default_spawn(project_root: Path) -> SpawnFn:
    """生产 spawn：主树直跑 ``claude -p``（与前置 SPEC 蒸馏 run 同形态，
    真相源是 spec 元数据层，非产品代码，不走 worktree 实现车道）。"""

    def _spawn(prompt: str, run_id: str) -> str:
        proc = subprocess.run(
            ["claude", "-p", prompt],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=SPAWN_TIMEOUT_SECONDS,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude -p 回填 run {run_id} 退出码 {proc.returncode}："
                f"{proc.stderr.strip()[-400:]}"
            )
        return proc.stdout

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
    return text


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
    return text.replace("{{VIOLATIONS_BLOCK}}", _violations_block(violations or []))


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


def scale_stats(project_root: Path) -> dict[str, int]:
    """真相源规模统计：域数 / 能力页数 / ADR 数 / 总行数（汇报与膨胀趋势共用）。"""
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
            lines += len(page.read_text(encoding="utf-8", errors="replace").splitlines())
    for nav in (kdir / "index.md",):
        if nav.is_file():
            lines += len(nav.read_text(encoding="utf-8", errors="replace").splitlines())
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
        if not cap or cap in chain_index:
            continue  # 已被归档覆盖：不写史前页（baseline 走链头输入）
        domain = str(item.get("domain") or "").strip()
        page = project_root / KNOWLEDGE_DIR / "domains" / domain / f"{cap}.md"
        if not page.is_file():
            missing.append(f"{cap}（域 {domain or '未声明'}）")
    return missing


def _clean_untracked_knowledge(project_root: Path, log) -> None:
    """自举重跑清场：清 ``spec/knowledge/`` 下未跟踪残留。

    e2e fixture 遗留（zn 演示域、fixture ADR、graph/ 产物）均为未跟踪文件；
    只动未跟踪内容（git clean），已入库内容不受影响——避免真实抽取的 ADR
    编号与 fixture 条目重复触发校验失败。
    """
    proc = subprocess.run(
        ["git", "clean", "-qfd", "--", KNOWLEDGE_DIR],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:  # noqa: BLE001 - fail-open 清理不阻塞自举
        log.warning(
            "knowledge",
            f"回填自举清理未跟踪残留失败（fail-open）：{proc.stderr.strip()[:200]}",
        )


def _prune_stale_domains(project_root: Path, domain_map: dict, log) -> list[str]:
    """以真实聚类重建域清单：不在新域集合中的既有域目录整体移除（fixture
    遗留域，如 zn-demo-domain）。Returns: 被移除的域名清单。"""
    domains_dir = project_root / KNOWLEDGE_DIR / "domains"
    removed: list[str] = []
    if not domains_dir.is_dir():
        return removed
    keep = {v for v in domain_map.values() if isinstance(v, str) and v}
    for d in sorted(domains_dir.iterdir()):
        if d.is_dir() and d.name not in keep:
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d.name)
    if removed:
        log.warning(
            "knowledge", f"回填自举重建域清单，移除遗留域：{', '.join(removed)}"
        )
    return removed


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

    chain_index = build_chain_index(project_root)
    ledger = BackfillLedger.load(project_root / LEDGER_RELPATH)
    ledger.reconcile(chain_index, archives)
    ledger.save()
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
            "scale": scale_stats(project_root),
        }

    domain_map_path = project_root / DOMAIN_MAP_RELPATH
    domain_map = _read_json(domain_map_path)
    if not isinstance(domain_map, dict) or not domain_map:
        # ── 聚类自举 run（v2：聚类对象从归档名改为链索引能力名）──
        # 自举重跑清场：fixture 遗留（未跟踪）先清，跑完再按真实聚类删遗留域
        _clean_untracked_knowledge(project_root, log)
        chain_caps = sorted(chain_index)
        prompt = build_prompt("bootstrap", capabilities=chain_caps)
        run_id = f"kb-bootstrap-{int(time.time())}"
        try:
            spawn(prompt, run_id)
        except Exception as e:  # noqa: BLE001 - fail-open 记台账不中断
            append_todo_line(
                project_root, f"回填聚类自举 run 失败（{run_id}）：{e}"
            )
            return {"triggered": True, "ok": False, "reason": "bootstrap-spawn-failed"}
        domain_map = _read_json(domain_map_path)
        if not isinstance(domain_map, dict) or not domain_map:
            append_todo_line(
                project_root,
                f"回填聚类自举 run（{run_id}）未产出域归位清单 {DOMAIN_MAP_RELPATH}，"
                "请人工检查后重跑回填",
            )
            return {"triggered": True, "ok": False, "reason": "bootstrap-no-domain-map"}
        _prune_stale_domains(project_root, domain_map, log)
        base_prompt = build_prompt("bootstrap", capabilities=chain_caps)
        ok, violations = _validate_with_repair(
            project_root, validate, spawn, base_prompt, run_id
        )
        if not ok:
            discard_knowledge_changes(project_root)
            append_todo_line(
                project_root,
                "回填自举产出校验 "
                f"{MAX_FIX_ROUNDS} 轮后仍失败，已放弃本次产出：{violations[:3]}",
            )
            return {
                "triggered": True,
                "ok": False,
                "reason": "bootstrap-invalid",
                "violations": violations[:10],
            }
        commit(project_root, [KNOWLEDGE_DIR], "[fenix] knowledge: backfill bootstrap")

    # ── 史前复原段（prehistoric bootstrap：git 考古 → 求差 → 史前页/链头）──
    prehistoric_path = project_root / PREHISTORIC_JSON_RELPATH
    inventory = _read_json(prehistoric_path)
    if not isinstance(inventory, list) or not inventory:
        prompt = build_prehistoric_prompt(project_root, chain_index)
        run_id = f"kb-prehistoric-{int(time.time())}"
        try:
            spawn(prompt, run_id)
        except Exception as e:  # noqa: BLE001 - fail-open 记台账不中断
            append_todo_line(project_root, f"回填史前复原 run 失败（{run_id}）：{e}")
            return {"triggered": True, "ok": False, "reason": "prehistoric-spawn-failed"}
        inventory = _read_json(prehistoric_path)
        if not isinstance(inventory, list) or not inventory:
            append_todo_line(
                project_root,
                f"回填史前复原 run（{run_id}）未产出史前清单 "
                f"{PREHISTORIC_JSON_RELPATH}，请人工检查后重跑回填",
            )
            return {"triggered": True, "ok": False, "reason": "prehistoric-no-inventory"}
        missing = _missing_prehistoric_pages(project_root, inventory, chain_index)
        if missing:
            append_todo_line(
                project_root,
                f"回填史前复原 run（{run_id}）未覆盖能力缺史前页："
                f"{', '.join(missing[:5])}，请人工检查后重跑回填",
            )
            return {"triggered": True, "ok": False, "reason": "prehistoric-missing-pages"}
        base_prompt = build_prehistoric_prompt(project_root, chain_index)
        ok, violations = _validate_with_repair(
            project_root, validate, spawn, base_prompt, run_id
        )
        if not ok:
            discard_knowledge_changes(project_root)
            append_todo_line(
                project_root,
                "回填史前复原产出校验 "
                f"{MAX_FIX_ROUNDS} 轮后仍失败，已放弃本次产出：{violations[:3]}",
            )
            return {
                "triggered": True,
                "ok": False,
                "reason": "prehistoric-invalid",
                "violations": violations[:10],
            }
        commit(project_root, [KNOWLEDGE_DIR], "[fenix] knowledge: backfill prehistoric")

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
    for i, batch in enumerate(batches, 1):
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
                project_root, validate, spawn, base_prompt, run_id
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
            for cap in batch:
                ledger.mark(CAPABILITY_PREFIX + cap, STATUS_DISTILLED, batch=i)
            ok_batches.append(i)
        else:
            discard_knowledge_changes(project_root)
            for cap in batch:
                ledger.mark(CAPABILITY_PREFIX + cap, STATUS_FAILED, batch=i)
            append_todo_line(
                project_root,
                f"回填批次 {i}/{total} 校验 {MAX_FIX_ROUNDS} 轮后仍失败（"
                f"{len(batch)} 个能力），已回滚半成品：{violations[:3]}",
            )
            failed_batches.append(
                {"batch": i, "capabilities": batch, "violations": violations[:5]}
            )
            log.warning(
                "knowledge",
                f"回填批次 {i}/{total} 失败（{len(batch)} 能力），继续后续批次",
            )
        ledger.save()

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
        base_prompt = build_prompt("adr", batch=batch)
        run_id = f"kb-adr{i}-{int(time.time())}"
        try:
            spawn(base_prompt, run_id)
            ok, violations = _validate_with_repair(
                project_root, validate, spawn, base_prompt, run_id
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
            for a in batch:
                ledger.mark(ADR_PREFIX + a, STATUS_DISTILLED, batch=i)
            adr_ok += 1
        else:
            discard_knowledge_changes(project_root)
            for a in batch:
                ledger.mark(ADR_PREFIX + a, STATUS_FAILED, batch=i)
            append_todo_line(
                project_root,
                f"回填 ADR 批次 {i}/{adr_total} 校验 {MAX_FIX_ROUNDS} 轮后仍失败"
                f"（{len(batch)} 个归档），已回滚半成品：{violations[:3]}",
            )
            adr_failed.append(
                {"batch": i, "archives": batch, "violations": violations[:5]}
            )
            log.warning(
                "knowledge",
                f"回填 ADR 批次 {i}/{adr_total} 失败（{len(batch)} 归档），继续后续批次",
            )
        ledger.save()

    counts = ledger.counts()
    scale = scale_stats(project_root)
    converged = all(
        c[STATUS_PENDING] == 0 and c[STATUS_FAILED] == 0 for c in counts.values()
    )
    summary = {
        "triggered": True,
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
    _write_report(project_root, summary)
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
) -> tuple[bool, list[str]]:
    """确定性校验 + 违规反馈修正环（≤MAX_FIX_ROUNDS 轮，对齐前置 SPEC 收尾校验）。"""
    violations = [str(v) for v in (validate(project_root) or [])]
    rounds = 0
    while violations and rounds < MAX_FIX_ROUNDS:
        rounds += 1
        # 修正 run 复用同一基础提示词（保留模式语境）+ 违规清单附加段
        spawn(
            base_prompt + "\n\n" + _violations_block(violations),
            f"{run_id}-fix{rounds}",
        )
        violations = [str(v) for v in (validate(project_root) or [])]
    return (not violations), violations


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
    summary = run_backfill(Path(args.project_root).resolve())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("ok", True) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
