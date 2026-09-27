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
（spec 元数据层非产品代码，无 merge-back）。
"""

from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("fenixd.knowledge")

# ── 路径与契约常数 ────────────────────────────────────────────────────

KNOWLEDGE_DIR = "spec/knowledge"
ARCHIVE_DIR = "spec/archive"
PROMPT_FILE = "knowledge_prompts/distill.md"  # 相对 core/ 包

# 单页 150 行硬顶（spec knowledge-atlas-directory「单页行数硬顶」）
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

# env 剔除口径同 SessionManager._BANNED_ENV_KEYS：蒸馏 run 与 agent-run 无关
_BANNED_ENV_KEYS = frozenset({
    "FENIX_RUN_PROJECT_ROOT",
    "FENIX_RUN_WORKTREE",
    "CLAUDE_CODE_ENABLE_TODO_TOOLS",
})


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
        try:
            _check_links(index_md.read_text(encoding="utf-8"), kroot, f"{KNOWLEDGE_DIR}/index.md")
        except (OSError, UnicodeDecodeError) as e:
            violations.append(f"{KNOWLEDGE_DIR}/index.md: 读取失败: {e}")

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
                    target = adr_dir / f"ADR-{target_num}-"
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
    return (
        f"{tpl}\n\n---\n\n"
        f"## 本次任务（动态段）\n\n"
        f"项目根（当前工作目录）：{proot}\n"
        f"真相源目录：{proot / KNOWLEDGE_DIR}\n\n"
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
        proc.communicate()
    except Exception:  # noqa: BLE001
        pass


def _register_todo_retry(proot: Path, archived_names: list, reason: str) -> None:
    """失败登 todo.md 重试台账（给人看的队列，不进任务门禁；fail-open）。"""
    names = ", ".join(archived_names)
    line = (
        f"- [ ] knowledge-distill 重试（{_utcnow_iso()}）：归档 {names} — {reason}\n"
    )
    section_head = "## knowledge-distill 重试台账\n"
    todo = proot / ".fenix" / "todo.md"
    try:
        todo.parent.mkdir(parents=True, exist_ok=True)
        existing = todo.read_text(encoding="utf-8") if todo.is_file() else ""
        if section_head not in existing:
            existing = existing.rstrip("\n") + ("\n\n" if existing.strip() else "") + section_head
        todo.write_text(existing + ("" if existing.endswith("\n") else "\n") + line, encoding="utf-8")
    except OSError as e:
        logger.warning("knowledge-distill 重试台账登记失败（todo.md 写入异常）: %s", e)


def _git(proot: Path, args: list, timeout: int = 60):
    return subprocess.run(
        ["git"] + args,
        cwd=str(proot),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _discard_output(proot: Path) -> None:
    """放弃产出：restore tracked + 清理未跟踪新增（不留半成品）。"""
    try:
        _git(proot, ["restore", "--", KNOWLEDGE_DIR])
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("knowledge-distill git restore 失败: %s", e)
    try:
        _git(proot, ["clean", "-f", "--", KNOWLEDGE_DIR])
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("knowledge-distill git clean 失败: %s", e)


def _commit_output(proot: Path, archived_names: list) -> str | None:
    """pathspec 限定自动提交（复用 archive_commit 的 fail-open 哲学）。

    Returns:
        commit hash（读取失败为 None）或 None（提交跳过/失败，已记 warning）。
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
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
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

        for round_no in range(1 + self._max_fix_rounds):
            result["rounds"] = round_no + 1
            if round_no > 0:
                # 修正轮：把违规清单回反馈给 run（design D2）
                prompt = build_distill_prompt(proot, archived_names) + (
                    "\n\n## 上一轮校验违规（必须逐条修正后重写相关文件）\n\n"
                    + "\n".join(f"- {v}" for v in violations)
                    + "\n"
                )
            ok, err = self._spawn_and_wait(proot, prompt)
            if not ok:
                result["error"] = err
                self._give_up(proot, archived_names, f"run 失败: {err}")
                return result
            violations = validate_knowledge(proot)
            if not violations:
                commit = _commit_output(proot, archived_names)
                result["ok"] = True
                result["commit"] = commit
                logger.info(
                    "knowledge-distill 完成（%s，第 %d 轮，commit=%s）",
                    names,
                    round_no + 1,
                    commit or "-",
                )
                return result
            logger.warning(
                "knowledge-distill 校验违规（%s，第 %d 轮）：%s",
                names,
                round_no + 1,
                "; ".join(violations[:5]),
            )

        # 修正轮耗尽仍违规 → 放弃产出
        self._give_up(proot, archived_names, "校验违规经 %d 轮修正仍未通过" % (result["rounds"]))
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
            proc.communicate(timeout=RUN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            _kill_process_group(proc)
            return False, f"run 超时（>{RUN_TIMEOUT_SECONDS}s），已终止进程组"
        except Exception as e:  # noqa: BLE001
            _kill_process_group(proc)
            return False, f"claude 进程通信失败: {e}"
        if proc.returncode != 0:
            return False, f"claude 进程非零退出（exit={proc.returncode}）"
        return True, None

    def _give_up(self, proot: Path, archived_names: list, reason: str) -> None:
        """放弃产出：清理半成品 + 登重试台账。"""
        _discard_output(proot)
        _register_todo_retry(proot, archived_names, reason)
        logger.warning(
            "knowledge-distill 放弃产出（%s）: %s；已清理 spec/knowledge/ 半成品并登重试台账",
            ", ".join(archived_names),
            reason,
        )


# 进程内单例（daemon / dashboard --serve 各进程一份；跨进程由 flock 兜底互斥）
_MANAGER = DistillManager()


def _get_dispatcher() -> DistillManager:
    return _MANAGER


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
        - False：reason ∈ disabled / archive-dir-missing / test-environment /
          error:<...>。
    """
    if _in_pytest() and dispatcher is None:
        # 测试环境守卫（task 2.3 测试隔离）：替身注入时绕开本守卫
        return {"dispatched": False, "reason": "test-environment"}

    proot = Path(project_root)

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

    # 归档目录存在性（蒸馏只读归档；软删除路径命名同样落 spec/archive/）
    if not (proot / ARCHIVE_DIR / archived_name).is_dir():
        return {"dispatched": False, "reason": "archive-dir-missing"}

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
    try:
        from core.config import ConfigLoader

        effective = config
        if effective is None:
            effective = ConfigLoader.resolve_config(proot)
        if not ConfigLoader.get_knowledge_config(effective or {})["enabled"]:
            return {"dispatched": False, "reason": "disabled"}
    except Exception as e:  # noqa: BLE001
        logger.warning("knowledge-distill 配置解析失败，跳过派发: %s", e)
        return {"dispatched": False, "reason": f"config-error: {e}"}
    missing = [n for n in archived_names if not (proot / ARCHIVE_DIR / n).is_dir()]
    if missing:
        return {"dispatched": False, "reason": f"archive-dir-missing: {', '.join(missing)}"}
    mgr = dispatcher or _get_dispatcher()
    try:
        mgr.dispatch(proot, list(archived_names))
        return {"dispatched": True, "reason": None}
    except Exception as e:  # noqa: BLE001
        logger.warning("knowledge-distill 批量派发失败: %s", e)
        _register_todo_retry(proot, list(archived_names), f"派发失败: {e}")
        return {"dispatched": False, "reason": f"error: {e}"}
