"""存量归档批量回填车道（add-knowledge-atlas-maintenance D1）。

前置 SPEC ``add-knowledge-atlas`` 的蒸馏管线只挂在「归档动作」上，存量归档不会再
被归档一次。本车道把 ``spec/archive/`` 全部存量归档按域聚类分批蒸馏回填真相源：

- 进度台账 ``.fenix/knowledge_backfill.jsonl``（每归档一行 pending/distilled/failed），
  断点重入：重跑只处理 pending 与 failed 条目；
- 首段「聚类自举 run」：一个 agent run 读全部归档的 specs 目录名 + proposal 标题，
  产出域骨架（``index.md`` / ``_domain.md``）与域归位清单；
- 第二段按域分批派发蒸馏 run（批 ≤20，code-fix 亲和性分批教训：批过大重做代价
  指数化），每批经 ``validate_knowledge`` 全量校验（≤2 轮修正反馈）后 pathspec
  限定提交 ``[fenix] knowledge: backfill batch N/total``；
- failed 批标 failed 并登记 todo.md，不阻塞后续批；全部条目终态后收敛，产出汇报，
  车道幂等（收敛后重入零派发）。

依赖：``core.knowledge``（前置 SPEC 交付）的 ``validate_knowledge`` 与提交工具函数
经延迟导入复用（任务 2.3，不修改 core/knowledge.py 本体）；前置未合并时车道整体
降级为单行日志跳过（fail-open，与蒸馏派发同哲学）。

激活方式：一次性批量车道，合并后手工激活（Migration Plan）——
``python3 -m core.knowledge_backfill --project-root <主树>``；daemon 不自动挂载，
避免合并即烧十几个蒸馏 run。
"""

from __future__ import annotations

import json
import os
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


# ── 进度台账 ─────────────────────────────────────────────────────────────


class BackfillLedger:
    """回填进度台账（``.fenix/knowledge_backfill.jsonl``，每归档一行）。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: dict[str, dict[str, Any]] = {}

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
        return ledger

    def reconcile(self, archive_names: list[str]) -> list[str]:
        """补登新出现的归档（pending）；返回本次新登名单。已终态条目不动。"""
        fresh = []
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        for name in archive_names:
            if name not in self.entries:
                self.entries[name] = {
                    "name": name,
                    "status": STATUS_PENDING,
                    "batch": None,
                    "updated_at": now,
                }
                fresh.append(name)
        return fresh

    def mark(self, name: str, status: str, batch: Optional[int] = None) -> None:
        entry = self.entries.get(name)
        if entry is None:
            entry = {"name": name, "status": status, "batch": batch}
            self.entries[name] = entry
        entry["status"] = status
        if batch is not None:
            entry["batch"] = batch
        entry["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    def pending_names(self) -> list[str]:
        """未终态条目（重入只处理 pending 与 failed）。"""
        return [
            name
            for name, e in sorted(self.entries.items())
            if e.get("status") in (STATUS_PENDING, STATUS_FAILED)
        ]

    def counts(self) -> dict[str, int]:
        out = {STATUS_PENDING: 0, STATUS_DISTILLED: 0, STATUS_FAILED: 0}
        for e in self.entries.values():
            out[e.get("status", STATUS_PENDING)] = out.get(e.get("status", STATUS_PENDING), 0) + 1
        return out

    def save(self) -> None:
        lines = [
            json.dumps(self.entries[name], ensure_ascii=False)
            for name in sorted(self.entries)
        ]
        atomic_write_text(self.path, "\n".join(lines) + ("\n" if lines else ""))


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
    archives: Optional[list[str]] = None,
    batch: Optional[list[str]] = None,
    violations: Optional[list[str]] = None,
) -> str:
    """提示词 = backfill.md 契约 + 动态段占位填充（模式线 / 清单 / 违规反馈）。"""
    text = PROMPT_PATH.read_text(encoding="utf-8")
    if mode == "bootstrap":
        archives = archives or []
        text = text.replace(
            "{{MODE_LINE}}",
            "本次运行模式：**模式一（聚类自举）**——只执行「模式一：聚类自举」段，"
            "忽略模式二。",
        )
        text = text.replace("{{ARCHIVE_COUNT}}", str(len(archives)))
        text = text.replace(
            "{{ARCHIVE_LIST}}",
            "\n".join(f"- {name}" for name in archives) or "（空）",
        )
        text = text.replace("{{BATCH_SIZE}}", "0")
        text = text.replace("{{BATCH_LIST}}", "（本次不适用）")
    elif mode == "batch":
        batch = batch or []
        text = text.replace(
            "{{MODE_LINE}}",
            "本次运行模式：**模式二（批量蒸馏批次）**——只执行「模式二：批量蒸馏"
            "批次」段，忽略模式一。",
        )
        text = text.replace("{{ARCHIVE_COUNT}}", "0")
        text = text.replace("{{ARCHIVE_LIST}}", "（本次不适用）")
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


# ── 批次划分与规模统计 ───────────────────────────────────────────────────


def build_batches(
    domain_map: dict[str, str], names: list[str]
) -> list[list[str]]:
    """按域分组、批 ≤20（同域一个批次流，域内超顶再切片；无域归位条目入
    ``_unassigned`` 兜底域）。确定性：域与归档均按名排序。"""
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

    ledger = BackfillLedger.load(project_root / LEDGER_RELPATH)
    ledger.reconcile(archives)
    ledger.save()
    todo_names = ledger.pending_names()

    # 收敛幂等：台账非空且全部终态 → 零派发只汇报
    if ledger.entries and not todo_names:
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
        # ── 聚类自举 run ──
        prompt = build_prompt("bootstrap", archives=archives)
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
        base_prompt = build_prompt("bootstrap", archives=archives)
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

    # ── 分批蒸馏 ──
    batches = build_batches(domain_map, todo_names)
    total = len(batches)
    ok_batches: list[int] = []
    failed_batches: list[dict] = []
    for i, batch in enumerate(batches, 1):
        base_prompt = build_prompt("batch", batch=batch)
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
            for name in batch:
                ledger.mark(name, STATUS_DISTILLED, batch=i)
            ok_batches.append(i)
        else:
            discard_knowledge_changes(project_root)
            for name in batch:
                ledger.mark(name, STATUS_FAILED, batch=i)
            append_todo_line(
                project_root,
                f"回填批次 {i}/{total} 校验 {MAX_FIX_ROUNDS} 轮后仍失败（"
                f"{len(batch)} 个归档），已回滚半成品：{violations[:3]}",
            )
            failed_batches.append(
                {"batch": i, "archives": batch, "violations": violations[:5]}
            )
            log.warning(
                "knowledge",
                f"回填批次 {i}/{total} 失败（{len(batch)} 归档），继续后续批次",
            )
        ledger.save()

    counts = ledger.counts()
    scale = scale_stats(project_root)
    converged = counts[STATUS_PENDING] == 0 and counts[STATUS_FAILED] == 0
    summary = {
        "triggered": True,
        "converged": converged,
        "batches_total": total,
        "batches_ok": len(ok_batches),
        "batches_failed": len(failed_batches),
        "failed": failed_batches,
        "counts": counts,
        "scale": scale,
    }
    _write_report(project_root, summary)
    log.info(
        "knowledge",
        f"回填车道收敛汇报：批 {len(ok_batches)}/{total} 成功、"
        f"{len(failed_batches)} 失败；规模 {scale}",
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
    failed = summary.get("failed", [])
    scale = summary.get("scale", {})
    lines = [
        "# 知识真相源存量回填汇报",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 批次总数：{summary.get('batches_total', 0)}"
        f"（成功 {summary.get('batches_ok', 0)} / 失败 {summary.get('batches_failed', 0)}）",
        f"- 归档台账：distilled {counts.get(STATUS_DISTILLED, 0)} / "
        f"failed {counts.get(STATUS_FAILED, 0)} / "
        f"pending {counts.get(STATUS_PENDING, 0)}",
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
                f"{', '.join(item['archives'])}"
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
