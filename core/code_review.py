"""core/code_review.py — 周期性代码审查车道：台账、指纹、状态机、窗口、manifest、SPEC 生成。

与每日自省同周期运行（design D3 同源口径），审查窗口内开发 SPEC 的代码
质量，问题沉淀为独立台账 ``.fenix/code-review/items.jsonl``，供项目页
「代码审查」分面展示与消费。

本模块为纯逻辑层，被 daemon（派发/收尾 ingest/核销）与 dashboard
（读取/状态流转/生成 SPEC）两侧复用；MUST NOT 派发 agent（派发职责在
daemon/admin_monitor 层）。

设计要点（add-code-review-agent-and-quality-tab）：
- 存储独立于 evolution 的 items.jsonl（语义不同，D2）；
- 指纹去重：``sha1(file|category|normalize_title(title))[:12]``；
- ``manual_full`` 全仓快照核销（D5），窗口审查只增不核销；
- 并发写复用 evolution 的 flock + 原子替换形态（_with_lock/_atomic_write）。
"""

import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_logger = logging.getLogger("fenixd.code_review")

# ── 台账路径常量 ─────────────────────────────────────────────────────


def code_review_dir(project_root) -> Path:
    """框架侧代码审查暂存区根目录（gitignored，非交付物）。"""
    return Path(project_root) / ".fenix" / "code-review"


def items_path(project_root) -> Path:
    return code_review_dir(project_root) / "items.jsonl"


def manifest_path(project_root, run_id: str) -> Path:
    """某次 review run 的 manifest 文件（派发时落盘，进度 total 权威来源）。"""
    return code_review_dir(project_root) / f"manifest-{run_id}.json"


def out_path(project_root, run_id: str) -> Path:
    """某次 review run 的增量输出文件（agent 逐文件追加，进度 done 来源）。"""
    return code_review_dir(project_root) / f"out-{run_id}.jsonl"


def _atomic_write(path: Path, content: str) -> None:
    """tempfile + fsync + os.replace 原子替换（StateMachine._write_all_locked 同式）。

    目录不存在时自动创建。写坏（中间被替换的文件内容）在系统层面不可能出现：
    rename 前文件不完整，rename 后旧内容消失。
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path_str = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(parent))
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(path))
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _with_lock(path: Path, fn):
    """在 path 同目录的 ``.<name>.lock`` 文件上加 flock 互斥后执行 fn。

    本台账同时被 daemon（run 收尾 ingest、全仓核销）与 dashboard
    （generate-spec 置 in_spec、items/status 置 ignored、清除归属）两侧写入，
    无锁的「读-改-写」会整批丢条目（evolution design「daemon 与 Dashboard
    同时写同一存储」即为此先例）。MUST NOT 在 fn 内再次加同一把锁。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / f".{path.name}.lock"
    with open(lock_path, "w") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


def _read_items_unlocked(path: Path) -> Dict[str, dict]:
    """锁内使用的 items.jsonl 读取（等价 read_items 但路径直传、不加锁）。"""
    out: Dict[str, dict] = {}
    if not path.is_file():
        return out
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            _logger.warning("code_review: items.jsonl 第 %s 行 JSON 损坏已跳过", lineno)
            continue
        if isinstance(rec, dict) and isinstance(rec.get("item_id"), str):
            out[rec["item_id"]] = rec
    return out


def read_items(project_root) -> Dict[str, dict]:
    """读取 ``.fenix/code-review/items.jsonl``，按 item_id 建索引返回 dict。

    文件不存在按空集合处理；单行 JSON 损坏记 WARNING 后跳过（MUST NOT 让
    整个读取失败——dashboard 列表端点依赖此容错）。
    """
    path = items_path(project_root)
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        _logger.warning("code_review: 读取 items.jsonl 失败: %s", e)
        return {}
    out: Dict[str, dict] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            _logger.warning("code_review: items.jsonl 第 %s 行 JSON 损坏已跳过: %s", lineno, e)
            continue
        if not isinstance(rec, dict) or not isinstance(rec.get("item_id"), str):
            continue
        out[rec["item_id"]] = rec
    return out


def write_items(project_root, records: Iterable[dict]) -> None:
    """全量写回 items.jsonl（读-改-写 + flock + 原子替换展开见 upsert_findings）。

    每条一行 JSON；调用方传入的 records 为 item_id→记录 dict 或可迭代记录。
    同一 item_id MUST 只保留一条（dict 天然保证）。
    """
    recs: Dict[str, dict] = {}
    for rec in records:
        if not isinstance(rec, dict) or not isinstance(rec.get("item_id"), str):
            continue
        recs[rec["item_id"]] = rec
    content = "".join(json.dumps(recs[k], ensure_ascii=False) + "\n" for k in sorted(recs))

    path = items_path(project_root)

    def _do() -> None:
        _atomic_write(path, content)

    _with_lock(path, _do)


# ── 指纹与归一化 ─────────────────────────────────────────────────────


def normalize_title(title: str) -> str:
    """标题归一化：去首尾空白、折叠内部连续空白为单空格、统一小写。

    保证同一问题跨轮 fingerprint 稳定（大小写/空白差异不产生新指纹）。
    """
    if not isinstance(title, str):
        title = str(title)
    return re.sub(r"\s+", " ", title.strip()).lower()


def fingerprint(file: str, category: str, title: str) -> str:
    """问题指纹：``sha1(f"{file}|{category}|{normalize_title(title)}")[:12]``。

    指纹去重权威（code-review-items 指纹去重场景）。
    """
    raw = f"{file}|{category}|{normalize_title(title)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _item_id(project: str, file: str, fp: str) -> str:
    """条目稳定 id：``sha1(project|file|fingerprint)[:12]``。

    同一问题重复观测不变（同一项目/文件/指纹 → 同 id）。
    """
    return hashlib.sha1(f"{project}|{file}|{fp}".encode("utf-8")).hexdigest()[:12]


def _now_iso() -> str:
    return datetime.now(timezone_utc()).isoformat()


def timezone_utc():
    """UTC timezone（延迟解析避免循环导入）。"""
    from datetime import timezone

    return timezone.utc


# ── 条目 upsert（读-改-写 + flock） ─────────────────────────────────


def upsert_findings(
    project_root, findings: List[dict], review_id: str, review_kind: str, spec_map: Optional[dict] = None
) -> dict:
    """按 fingerprint 去重写入审查发现到台账（读-改-写 + flock 原子）。

    ``findings``: agent 逐文件审查产出的结构化发现列表，每条至少含
        file / category / title / severity / description / suggestion /
        evidence / line（可选，缺省 1）。
    ``review_id``: 本次 review run 的 run_id（code-review-<epoch>）。
    ``review_kind``: scheduled / manual_full / manual_window。
    ``spec_map``: fingerprint → spec_name 映射（可选，ingest 时已关联修复
        SPEC 的条目直接带归属）。

    去重语义：同 fingerprint 已存在 → 仅刷新 last_seen_at / severity /
    description / suggestion（MUST NOT 覆盖 status / spec_name /
    first_seen_at）；不存在 → 插入新条目（status=open，first_seen_at ==
    last_seen_at == now）。

    Returns: ``{"inserted": n, "updated": n}``
    """
    spec_map = spec_map or {}
    now = _now_iso()
    project = str(Path(project_root).name) or str(project_root)
    path = items_path(project_root)
    inserted = 0
    updated = 0

    def _do() -> None:
        nonlocal inserted, updated
        current = _read_items_unlocked(path)
        by_fp: Dict[str, dict] = {}
        for rec in current.values():
            fp = rec.get("fingerprint")
            if isinstance(fp, str):
                by_fp[fp] = rec
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            file_ = str(finding.get("file") or "")
            category = str(finding.get("category") or "")
            title = str(finding.get("title") or "")
            if not file_ or not title:
                # 缺关键字段的发现跳过（不整批失败）
                continue
            fp = fingerprint(file_, category, title)
            rec = by_fp.get(fp)
            base = {
                "file": file_,
                "line": int(finding.get("line") or 1),
                "severity": str(finding.get("severity") or "info"),
                "category": category,
                "title": title,
                "description": str(finding.get("description") or ""),
                "suggestion": str(finding.get("suggestion") or ""),
                "evidence": str(finding.get("evidence") or ""),
                "fingerprint": fp,
            }
            if rec is None:
                rec = {
                    "item_id": _item_id(project, file_, fp),
                    "project": project,
                    "review_id": review_id,
                    "review_kind": review_kind,
                    "reviewed_at": now,
                    "spec": str(finding.get("spec") or ""),
                    "status": "open",
                    "spec_name": spec_map.get(fp),
                    "first_seen_at": now,
                    "last_seen_at": now,
                }
                rec.update(base)
                current[rec["item_id"]] = rec
                by_fp[fp] = rec
                inserted += 1
            else:
                # 已存在：仅刷新可变字段，状态/归属/首见时间不动
                rec.update(base)
                rec["last_seen_at"] = now
                rec["review_id"] = review_id
                rec["review_kind"] = review_kind
                rec["reviewed_at"] = now
                if not rec.get("spec_name") and spec_map.get(fp):
                    rec["spec_name"] = spec_map[fp]
                updated += 1
        content = "".join(
            json.dumps(current[k], ensure_ascii=False) + "\n" for k in sorted(current)
        )
        _atomic_write(path, content)

    _with_lock(path, _do)
    return {"inserted": inserted, "updated": updated}


def resolve_snapshot(project_root, observed_fingerprints: set, now: Optional[str] = None) -> int:
    """全仓快照核销：open 且本轮未再观测到的条目置 resolved。

    调用方保证仅在 ``review_kind == "manual_full"`` 时调用（本函数不做
    review_kind 判定，核销职责在 run_code_review 收尾分支）。

    核销语义：台账中 ``status == "open"`` 且 fingerprint 不在
    ``observed_fingerprints`` 中的条目置 ``resolved``（记录 resolved_at）；
    MUST NOT 触碰 ``in_spec`` / ``ignored``（全仓快照核销场景）。

    Returns: 被核销的条目数。
    """
    now = now or _now_iso()
    path = items_path(project_root)
    resolved_count = 0

    def _do_locked() -> None:
        nonlocal resolved_count
        current = _read_items_unlocked(path)
        changed = False
        for rec in current.values():
            if rec.get("status") != "open":
                continue
            fp = rec.get("fingerprint")
            if isinstance(fp, str) and fp in observed_fingerprints:
                continue
            rec["status"] = "resolved"
            rec["resolved_at"] = now
            rec["last_seen_at"] = now
            changed = True
        if changed:
            content = "".join(
                json.dumps(current[k], ensure_ascii=False) + "\n" for k in sorted(current)
            )
            _atomic_write(path, content)
        resolved_count = sum(1 for r in current.values() if r.get("resolved_at") == now)

    _with_lock(path, _do_locked)
    return resolved_count


def set_item_status(project_root, item_id: str, status: str, spec_name: Optional[str] = None) -> dict:
    """人工状态流转（幂等）：``open`` / ``ignored`` 为人工可置状态。

    ``resolved`` 由全仓核销置入，``in_spec`` 由生成链路置入，二者 MUST NOT
    经本函数人工置入（本函数对这些值返回错误）。从 ``in_spec`` 重置回
    ``open`` 时 MUST 同时清空 ``spec_name``。未知 item_id 返回错误不抛异常。

    Returns: ``{"ok": bool, "item_id": ..., "status": ..., "error": str|null}``
    """
    if status not in ("open", "ignored"):
        return {
            "ok": False,
            "item_id": item_id,
            "status": status,
            "error": f"状态 {status!r} 不可经人工流转置入（仅 open/ignored）",
        }
    path = items_path(project_root)

    def _impl() -> dict:
        current = _read_items_unlocked(path)
        rec = current.get(item_id)
        if rec is None:
            return {
                "ok": False,
                "item_id": item_id,
                "status": status,
                "error": f"条目不存在: {item_id}",
            }
        prev = rec.get("status")
        if prev == status:
            # 幂等：重复标记同一状态不报错、无副作用
            return {"ok": True, "item_id": item_id, "status": status, "error": None, "idempotent": True}
        rec["status"] = status
        if status == "open" and prev == "in_spec":
            # 清除归属：in_spec → open 时清空 spec_name
            rec["spec_name"] = None
        if spec_name is not None:
            rec["spec_name"] = spec_name
        content = "".join(
            json.dumps(current[k], ensure_ascii=False) + "\n" for k in sorted(current)
        )
        _atomic_write(path, content)
        return {"ok": True, "item_id": item_id, "status": status, "error": None}

    result = {}
    _with_lock(path, lambda: result.update(_impl()))
    return result


# ── 周期窗口（与自省同源） ─────────────────────────────────────────


def _read_json_file(path: Path) -> dict:
    """读取 JSON 文件；缺失/损坏返回空 dict。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _iso_to_local_dt(iso_str: Optional[str]) -> Optional[datetime]:
    """ISO 时间戳（含 Z 后缀）→ 本地 naive datetime；解析失败返回 None。"""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def compute_window(project_root, now: Optional[datetime] = None) -> Tuple[datetime, str]:
    """周期窗口起点：读 ``.fenix/self_review_state.json`` 的 ``last_run_at``。

    与 ``core/self_review.py`` 的窗口计算同源口径（MUST NOT 另立周期逻辑）：
    ``last_run_at`` 存在 → 窗口起点为该时刻；缺失（首跑/旧格式）→ 回退
    ``now - 24h``。返回 ``(window_start, window_kind)``，window_kind 为
    ``"last_run"`` 或 ``"fallback"``（供日志/审计区分）。
    """
    now = now or datetime.now()
    state = _read_json_file(Path(project_root) / ".fenix" / "self_review_state.json")
    last_run_at = _iso_to_local_dt(state.get("last_run_at"))
    if last_run_at is not None:
        return last_run_at, "last_run"
    return now - timedelta(hours=24), "fallback"


# ── manifest 收集 ──────────────────────────────────────────────────


_SOURCE_EXTS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".css",
}
_EXCLUDED_DIRS = {
    "spec",
    "docs",
    "dist",
    ".fenix",
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "archive",
    "static/dist",
    # 测试代码不作为审查对象（2026-09-19 用户决策）：审查面对准产品代码。
    # 全仓 474 文件里 tests/ 占 251，且过半是断言细节而非产品逻辑——
    # 逐文件 LLM 审查既稀释了产品代码的注意力预算，也让 manifest 规模失去意义。
    # 测试自身的质量由测试套件自身把关。
    "tests",
}
_EXCLUDED_PREFIXES = (
    "spec/",
    "docs/",
    "dist/",
    ".fenix/",
    ".git/",
    "tests/",
    "core/dashboard/static/dist/",
)
# 生成物文件名判据（无法靠目录排除的）：``*.gen.css`` 等由构建命令产出
# （如 tailwind.gen.css 由 package.json 的 prebuild 生成），审查它们是
# 对压缩产物做 LLM 审查，无意义且极烧 token（单文件逾 1 万字符）。
_GENERATED_NAME_MARKERS = (".gen.", ".min.")
_GENERATED_SUFFIXES = (".d.ts",)


def _is_source_file(path_str: str) -> bool:
    """判定是否为受控产品源码文件（排除测试/文档/生成物/运行时产物）。

    排除维度：目录前缀（spec/docs/dist/.fenix/tests）、路径中出现的排除目录名、
    扩展名白名单、以及生成物文件名判据（``.gen.`` / ``.min.`` / ``.d.ts``）。
    """
    p = path_str.replace("\\", "/")
    for prefix in _EXCLUDED_PREFIXES:
        if p.startswith(prefix):
            return False
    parts = p.split("/")
    for part in parts:
        if part in _EXCLUDED_DIRS:
            return False
    name = parts[-1].lower() if parts else ""
    for marker in _GENERATED_NAME_MARKERS:
        if marker in name:
            return False
    for suffix in _GENERATED_SUFFIXES:
        if name.endswith(suffix):
            return False
    ext = Path(p).suffix.lower()
    return ext in _SOURCE_EXTS


def _git(project_root, args: List[str]) -> str:
    """执行 git 命令（cwd=project_root），返回 stdout；失败返回空串。"""
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root)] + args,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        _logger.warning("code_review: git %s 执行失败: %s", args[0], e)
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout


def collect_manifest(project_root, scope: str, window_start: Optional[datetime] = None) -> List[str]:
    """收集待审文件清单（manifest）。

    scope="window"：收集 ``window_start`` 之后合并/产出到主树的 SPEC 所
        变更文件（``git log --since`` + ``--name-only`` 推导）。
    scope="full"：收集全仓受控源码文件（``git ls-files``，排除
        spec/ docs/ dist/ .fenix/ 等非代码路径）。

    manifest 为空时 MUST NOT 返回「全绿」语义——返回空列表，由调用方
    明确置 ``no_files``（design Risk「空场景/空 manifest 白洗」）。
    """
    if scope == "full":
        raw = _git(project_root, ["ls-files"])
        files = [line for line in raw.splitlines() if line.strip()]
    else:
        # 窗口：window_start 之后变更的文件（--since 走本地时间）
        since = window_start.isoformat() if window_start is not None else None
        if since is None:
            return []
        raw = _git(project_root, ["log", "--since", since, "--name-only", "--pretty=format:"])
        files = [line for line in raw.splitlines() if line.strip()]
    seen: set = set()
    out: List[str] = []
    for f in files:
        f = f.strip()
        if not f or f in seen:
            continue
        seen.add(f)
        if _is_source_file(f):
            out.append(f)
    return out


# ── 进度读取（真实进度，D4） ───────────────────────────────────────


def _latest_review_run(project_root) -> Optional[str]:
    """最新一次 review run 的 run_id（按内嵌 epoch 排序），无则 None。"""
    d = code_review_dir(project_root)
    if not d.is_dir():
        return None
    latest: Optional[str] = None
    latest_ts = -1
    try:
        for p in d.glob("manifest-*.json"):
            name = p.name[len("manifest-") : -len(".json")]
            m = re.search(r"(\d{9,10})$", name)
            if not m:
                continue
            ts = int(m.group(1))
            if ts > latest_ts:
                latest_ts = ts
                latest = name
    except OSError:
        pass
    return latest


def read_progress(project_root) -> dict:
    """读取当前 code-review 运行进度。

    Returns: ``{running, review_id, review_kind, total, done, current}``
    - ``done`` = 对应 run 的 out jsonl 行数；
    - ``total`` = 派发时落盘的 manifest-<review_id>.json 长度；
    - ``current`` = 最后一行落盘的文件名；
    - ``running`` 判定：取最新一个 run（按 review_id 内嵌 epoch 排序），
      仅当该 run 的 ``.fenix/runs/<review_id>.jsonl`` 末行非终态（无
      result/error/interrupted/cancelled 终态行）且产物 mtime 未超既有
      stale 阈值时 ``running=true``；已有终态行或超时即 ``running=false``
      （对齐 core/dashboard/data/runs.py 的 _classify_run/_RUN_STALE_SECONDS
      同款口径）。终态集合取 _RUN_TERMINAL_STATUS_MAP 全量（result/error/
      interrupted/cancelled/superseded）。
    """
    base = {"running": False, "review_id": None, "review_kind": None,
            "total": 0, "done": 0, "current": None}
    run_id = _latest_review_run(project_root)
    if run_id is None:
        return base
    # 读 manifest（total 权威来源）
    mpath = manifest_path(project_root, run_id)
    try:
        mdata = _read_json_file(mpath)
    except Exception:
        mdata = {}
    files = mdata.get("files") if isinstance(mdata.get("files"), list) else []
    total = len(files)
    review_kind = mdata.get("review_kind")
    # 读 out jsonl（done/current）
    opath = out_path(project_root, run_id)
    done = 0
    current = None
    if opath.is_file():
        try:
            lines = opath.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        done = len([l for l in lines if l.strip()])
        if lines:
            try:
                last = json.loads(lines[-1])
                if isinstance(last, dict):
                    current = last.get("file") or last.get("title") or None
            except (json.JSONDecodeError, IndexError):
                current = None
    # running 判定（终态 + stale 阈值，对齐 runs.py 口径）
    running = False
    run_file = Path(project_root) / ".fenix" / "runs" / f"{run_id}.jsonl"
    if run_file.is_file():
        try:
            last_line = run_file.read_text(encoding="utf-8", errors="replace").splitlines()[-1]
            last_ev = json.loads(last_line)
        except (OSError, IndexError, json.JSONDecodeError):
            last_ev = None
        terminal = _terminal_status_map()
        if isinstance(last_ev, dict) and last_ev.get("type") in terminal:
            running = False
        else:
            # 末行非终态 → 看 mtime 是否超 stale 阈值
            try:
                age = datetime.now().timestamp() - run_file.stat().st_mtime
            except OSError:
                age = 10**9
            running = age <= _run_stale_seconds()
    return {
        "running": running,
        "review_id": run_id,
        "review_kind": review_kind,
        "total": total,
        "done": done,
        "current": current,
    }


def _terminal_status_map() -> dict:
    """run 终态事件类型集合（result/error/interrupted/cancelled/superseded）。

    对齐 core/dashboard/data/runs.py:_RUN_TERMINAL_STATUS_MAP（延迟解析
    避免 core.dashboard 导入链）。
    """
    from core.dashboard.data.runs import _RUN_TERMINAL_STATUS_MAP

    return dict(_RUN_TERMINAL_STATUS_MAP)


def _run_stale_seconds() -> float:
    """run 产物 stale 阈值（对齐 runs.py:_RUN_STALE_SECONDS）。"""
    from core.dashboard.data.runs import _RUN_STALE_SECONDS

    return float(_RUN_STALE_SECONDS)


def local_today_str() -> str:
    """本地自然日字符串 YYYY-MM-DD（状态文件同日防重复基准，与自省同源）。"""
    return datetime.now().date().isoformat()


def _code_review_state_path(project_root) -> Path:
    return Path(project_root) / ".fenix" / "code_review_state.json"


def read_code_review_state(project_root) -> dict:
    """读取 ``.fenix/code_review_state.json``（同日防重状态）。"""
    return _read_json_file(_code_review_state_path(project_root))


def save_code_review_state(project_root, date_str: str) -> None:
    """写入 ``.fenix/code_review_state.json`` 的 last_run_date（同日防重）。

    与自省状态文件解耦（MUST NOT 复用 self_review_state.json 的
    last_run_date——会被同轮自省检查点写为今天导致本车道永不派发）。
    """
    path = _code_review_state_path(project_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "last_run_date": date_str,
                    "updated_at": datetime.now().astimezone().isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as e:
        _logger.warning("code_review: code_review_state.json 写入失败: %s", e)


# ── 修复 SPEC 生成（复用 evolution 链路，分组 6） ──────────────────

_KEBAB_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SPEC_YAML_TEMPLATE = "schema: spec-driven\ncreated: {created}\nmode: full\n"


def _spec_yaml_content(created: str) -> str:
    """生成 .spec.yaml 内容（f-string 组装；`.format()` 实参为关键字、
    arity-guard 无法解析会误报「实参必填位不足」，故用 f-string 展开）。"""
    return f"schema: spec-driven\ncreated: {created}\nmode: full\n"


def _slugify(text: str) -> str:
    """把任意文本推导为 kebab-case slug（^[a-z0-9][a-z0-9-]*$）。"""
    if not isinstance(text, str):
        text = str(text)
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    if not s:
        s = "fix"
    if not s[0].isdigit() and not s[0].isalpha():
        s = "fix-" + s
    return s


def _spec_name_conflicted(project_root, state_machine, candidate: str) -> bool:
    """三处判重：spec/changes/<cand>、STATE 既有条目名、spec/archive/*-<cand>。

    与 evolution resolve_spec_name 同源口径。
    """
    proot = Path(project_root)
    if (proot / "spec" / "changes" / candidate).is_dir():
        return True
    if state_machine is not None:
        try:
            if candidate in state_machine.read_all():
                return True
        except Exception as e:
            _logger.warning("code_review: 读取 STATE 判定重名失败: %s", e)
    arch_root = proot / "spec" / "archive"
    if arch_root.is_dir():
        try:
            for archived in arch_root.iterdir():
                if not archived.is_dir():
                    continue
                if archived.name == candidate or archived.name.endswith(f"-{candidate}"):
                    return True
        except OSError:
            pass
    return False


def _resolve_fix_spec_name(project_root, state_machine, slug: str, first_fp: str) -> Optional[str]:
    """修复 SPEC 命名消解：基名 ``fix-cr-<slug>``，冲突追加 ``-<fp[:6]>``。

    仍冲突返回 None（调用方返回错误不覆盖）。
    """
    if not isinstance(slug, str) or not _KEBAB_RE.match(slug):
        return None
    candidate = f"fix-cr-{slug}"
    if _spec_name_conflicted(project_root, state_machine, candidate):
        candidate = f"fix-cr-{slug}-{str(first_fp)[:6]}"
        if _spec_name_conflicted(project_root, state_machine, candidate):
            return None
    return candidate


def _normalize_start_after(value) -> Tuple[bool, Optional[str], str]:
    """归一化 ``start_after`` 三态（与 ``set_spec_start_after`` 同源口径）。

    Returns: ``(ok, normalized, error)``——ok=False 时 normalized 无意义。
    - None / 空串 → ``(True, None, "")``（立即执行）
    - ``"manual"``（大小写不敏感 + strip）→ ``(True, "manual", "")``（待激活哨兵，
      跳过 ``parse_utc``——哨兵不是时间）
    - 合法 ISO8601 → ``(True, <归一 ISO>, "")``
    - 其它 → ``(False, None, <错误文案>)``（调用方拒绝写入，不半写）
    """
    from core.state_machine import parse_utc

    if value is None or (isinstance(value, str) and not value.strip()):
        return True, None, ""
    if isinstance(value, str) and value.strip().lower() == "manual":
        return True, "manual", ""
    dt = parse_utc(value) if isinstance(value, str) else None
    if dt is None:
        return False, None, f"start_after 非法 ISO8601: {value!r}"
    return True, dt.isoformat(), ""


def generate_fix_spec(
    project_root, state_machine, item_ids: List[str], start_after=None
) -> dict:
    """从选中问题条目机械合成为一个修复 SPEC（复用 evolution 链路）。

    - 筛出 ``status == "open"`` 且 ``file`` 非空的选中条目（其余进 skipped，
      不整批失败）；无有效条目返回错误；
    - ``start_after`` 三态（None/空 = 立即执行，``"manual"`` = 待激活哨兵，
      ISO8601 = 定时拾取）经 ``_normalize_start_after`` 归一后随 entry 注册；
      非法值在落盘**之前**拒绝（不半写）；
    - 复用 core.deliverables.lint_declared / lint_tasks_parseable 同源 lint
      预检，违规则删除草稿、返回错误、条目状态不变（不半写）；
    - 命名 ``fix-cr-<slug>``（slug 由首个条目 category/短标题推导），冲突
      追加 ``-<fingerprint[:6]>`` 重试；判重覆盖 spec/changes / STATE /
      spec/archive 三处；仍冲突返回错误不覆盖；
    - 落地：复制草稿到 spec/changes/<name> → git add+commit → add_spec
      (drafted, priority=5[, start_after])；成功后参与条目置 in_spec 并写 spec_name；
    - 幂等：同批 item_ids 已成功（全部 in_spec 且同 spec_name）时返回既有
      spec_name，不重复生成。

    Returns: ``{"ok": bool, "spec_name": str|null, "skipped": [..],
              "error": str|null, "start_after": str|null}``
    """
    ok_sa, normalized_sa, sa_err = _normalize_start_after(start_after)
    if not ok_sa:
        return {
            "ok": False,
            "spec_name": None,
            "skipped": [],
            "error": sa_err,
            "start_after": None,
        }

    items = read_items(project_root)
    candidates: List[dict] = []
    skipped: List[dict] = []
    in_spec_names: set = set()
    for item_id in item_ids:
        rec = items.get(item_id)
        if rec is None:
            skipped.append({"item_id": item_id, "reason": "条目不存在"})
            continue
        status = rec.get("status")
        if status == "in_spec" and rec.get("spec_name"):
            in_spec_names.add(str(rec["spec_name"]))
            skipped.append({"item_id": item_id, "reason": "already_in_spec"})
            continue
        if status != "open":
            skipped.append({"item_id": item_id, "reason": f"status={status}"})
            continue
        if not rec.get("file"):
            skipped.append({"item_id": item_id, "reason": "缺 file 字段"})
            continue
        candidates.append(rec)

    if not candidates:
        # 幂等：全部已 in_spec 且同一 spec_name → 返回既有结果
        if len(in_spec_names) == 1:
            return {
                "ok": True,
                "spec_name": next(iter(in_spec_names)),
                "skipped": skipped,
                "error": None,
                "start_after": normalized_sa,
                "idempotent": True,
            }
        return {
            "ok": False,
            "spec_name": None,
            "skipped": skipped,
            "error": "无有效的 open 条目可生成",
            "start_after": None,
        }

    # slug 推导（首个候选的 category 或短标题）
    first = candidates[0]
    slug = _slugify(str(first.get("category") or "") or str(first.get("title") or ""))
    if not _KEBAB_RE.match(slug):
        slug = _slugify(str(first.get("title") or ""))
    first_fp = str(first.get("fingerprint") or "")
    name = _resolve_fix_spec_name(project_root, state_machine, slug, first_fp)
    if name is None:
        return {
            "ok": False,
            "spec_name": None,
            "skipped": skipped,
            "error": f"SPEC 名冲突无法消解（base fix-cr-{slug}）",
        }

    capability = slug or "fix"
    created = datetime.now().astimezone().strftime("%Y-%m-%d")
    draft_root = code_review_dir(project_root) / "drafts" / name
    try:
        shutil.rmtree(draft_root, ignore_errors=True)
        draft_root.mkdir(parents=True, exist_ok=True)
        spec_sub = draft_root / "specs" / capability
        spec_sub.mkdir(parents=True, exist_ok=True)
        (draft_root / "proposal.md").write_text(
            _proposal_md(name, candidates), encoding="utf-8"
        )
        (spec_sub / "spec.md").write_text(
            _spec_md(capability, candidates), encoding="utf-8"
        )
        (draft_root / "design.md").write_text(
            _design_md(name, candidates), encoding="utf-8"
        )
        (draft_root / "tasks.md").write_text(
            _tasks_md(name, candidates), encoding="utf-8"
        )
        (draft_root / ".spec.yaml").write_text(
            _spec_yaml_content(created), encoding="utf-8"
        )
    except OSError as e:
        shutil.rmtree(draft_root, ignore_errors=True)
        return {"ok": False, "spec_name": None, "skipped": skipped, "error": f"草稿落盘失败: {e}"}

    # 同源 lint 预检（violation → 删除草稿、条目状态不变、返回错误）
    violations = _lint_draft(draft_root, project_root)
    if violations:
        shutil.rmtree(draft_root, ignore_errors=True)
        return {
            "ok": False,
            "spec_name": None,
            "skipped": skipped,
            "error": f"lint 未通过: {'；'.join(violations)}",
        }

    # 落地：复制到 spec/changes → git add+commit → add_spec
    dest = Path(project_root) / "spec" / "changes" / name
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    try:
        shutil.copytree(draft_root, dest)
    except OSError as e:
        shutil.rmtree(draft_root, ignore_errors=True)
        return {"ok": False, "spec_name": None, "skipped": skipped, "error": f"复制到 spec/changes 失败: {e}"}

    ok, err = _git_commit(project_root, dest, name)
    if not ok:
        shutil.rmtree(dest, ignore_errors=True)
        shutil.rmtree(draft_root, ignore_errors=True)
        return {"ok": False, "spec_name": None, "skipped": skipped, "error": f"git commit 失败: {err}"}

    registered = False
    try:
        if state_machine is not None:
            registered = state_machine.add_spec(name, {"status": "drafted", "priority": 5})
        else:
            registered = True
    except Exception as e:
        _logger.warning("code_review: 注册 %s 失败: %s", name, e)
        registered = False

    if not registered:
        # 注册失败：清理草稿（已提交的 spec/changes 保留，供人工处置）
        shutil.rmtree(draft_root, ignore_errors=True)
        return {
            "ok": False,
            "spec_name": name,
            "skipped": skipped,
            "error": f"STATE 注册失败（spec/changes/{name} 已提交，可人工处置）",
        }

    shutil.rmtree(draft_root, ignore_errors=True)

    # 成功后把参与条目置 in_spec 并写 spec_name（in_spec 由生成链路置入，
    # 不经 set_item_status——后者仅允许人工 open/ignored，design 1.5）
    _mark_in_spec(project_root, [rec["item_id"] for rec in candidates], name)
    return {"ok": True, "spec_name": name, "skipped": skipped, "error": None}


def _mark_in_spec(project_root, item_ids: List[str], spec_name: str) -> None:
    """把条目置 in_spec 并写入 spec_name（生成链路内部写路径，读-改-写锁内原子）。"""
    path = items_path(project_root)

    def _do() -> None:
        current = _read_items_unlocked(path)
        for iid in item_ids:
            rec = current.get(iid)
            if rec is None:
                continue
            rec["status"] = "in_spec"
            rec["spec_name"] = spec_name
        content = "".join(
            json.dumps(current[k], ensure_ascii=False) + "\n" for k in sorted(current)
        )
        _atomic_write(path, content)

    _with_lock(path, _do)


def _indent_block(text: str, prefix: str = "  ") -> List[str]:
    """把多行文本逐行加前缀（空行保留为裸空行），供嵌入 Markdown 列表。

    描述/证据字段可能含换行（实测台账存在多行 description）。直接内插会破坏
    列表缩进或撞上 tasks.md 的行首正则，故一律逐行加前缀后再拼接。
    """
    if not text:
        return []
    return [f"{prefix}{ln}" if ln.strip() else "" for ln in str(text).splitlines()]


def _problem_lines(it: dict, detail_prefix: str = "  ") -> List[str]:
    """单条问题的结构化详情块（严重度 / 位置 / 描述 / 建议 / 证据）。

    修复 agent 需要问题**内容**而不仅是标题：只给一行标题会丢失
    description 里的复现路径与建议（2026-09-20 用户反馈）。四字段各自可选
    ——suggestion 实测大量为空，缺失时整段不渲染。
    """
    lines: List[str] = []
    for label, key in (("问题描述", "description"), ("修复建议", "suggestion"), ("证据", "evidence")):
        value = str(it.get(key) or "").strip()
        if not value:
            continue
        lines.append(f"{detail_prefix}**{label}**：")
        lines.append("")
        lines.extend(_indent_block(value, detail_prefix))
        lines.append("")
    return lines


def _unique_deliverable_paths(items: List[dict]) -> List[str]:
    """去重后的交付路径清单（按首次出现顺序）。

    多个问题可能指向同一文件，逐条声明会写出重复 ``path:`` 条目。
    """
    seen: List[str] = []
    for it in items:
        path = str(it.get("file") or "").strip()
        if path and path not in seen:
            seen.append(path)
    return seen


def _proposal_md(name: str, items: List[dict]) -> str:
    lines = [
        "## Why",
        "",
        "代码审查发现问题修复 SPEC（由 code-review 台账选中条目机械生成）。",
        "",
        "## What Changes",
        "",
        f"- 修复以下审查发现（SPEC `{name}`）：",
        "",
    ]
    for it in items:
        lines.append(f"### [{it.get('severity')}] {it.get('title')}")
        lines.append("")
        lines.append(f"- 类别：`{it.get('category')}`")
        lines.append(f"- 位置：`{it.get('file')}:{it.get('line')}`")
        lines.append("")
        lines.extend(_problem_lines(it, ""))
    lines += [
        "## Capabilities",
        "",
        "### New Capabilities",
        "",
        "- 修复 code-review 台账中选中的代码质量问题。",
        "",
        "## Impact",
        "",
        "- 修改 `## Deliverables` 声明段所列文件。",
        "",
    ]
    return "\n".join(lines)


def _spec_md(capability: str, items: List[dict]) -> str:
    lines = [
        "# Spec Delta: " + capability,
        "",
        "## ADDED Requirements",
        "",
        "### Requirement: 修复选中的代码审查问题",
        "",
        "系统 SHALL 修复以下 code-review 台账选中的问题：",
        "",
    ]
    for it in items:
        lines.append(f"#### `{it.get('file')}:{it.get('line')}` — {it.get('title')}")
        lines.append("")
        lines.append(f"- 严重度：{it.get('severity')}")
        lines.append("")
        lines.extend(_problem_lines(it, ""))
    lines += [
        "#### Scenario: 修复完成",
        "",
        "- **WHEN** 修复提交",
        "- **THEN** 对应问题不再出现在 code-review open 列表",
        "",
    ]
    return "\n".join(lines)


def _design_md(name: str, items: List[dict]) -> str:
    lines = [
        f"# Design: {name}",
        "",
        "## Context",
        "",
        "由 code-review 台账选中问题机械生成的修复 SPEC。",
        "",
        "## Decisions",
        "",
        "- 逐条修复选中问题，目标文件见 Deliverables 声明。",
        "",
        "## 逐条修复方向",
        "",
    ]
    for it in items:
        lines.append(f"### `{it.get('file')}:{it.get('line')}` — {it.get('title')}")
        lines.append("")
        lines.extend(_problem_lines(it, ""))
    return "\n".join(lines)


def _tasks_md(name: str, items: List[dict]) -> str:
    lines = [
        f"# Tasks: {name}",
        "",
        "## Deliverables",
        "",
        "```yaml",
    ]
    for path in _unique_deliverable_paths(items):
        lines.append(f"- path: {path}")
        lines.append("  kind: modify")
    lines += [
        "```",
        "",
        "## 1. 修复审查问题",
        "",
    ]
    for idx, it in enumerate(items, start=1):
        # 行首形态 MUST 保持 `- [ ] <编号>. <短标题>`：parse_tasks_md 的
        # `^- \[(x| )\] (\d+\.\d+[a-z]?)` 与产物归属 lint 都只认行首，
        # 破坏它等于任务清单在进度跟踪里静默消失（tasks.md 分组格式漂移事故）。
        # 完整内容一律以缩进子项挂在任务行下（缩进后不匹配 `^- \[`，也不
        # 参与归属校验）。
        lines.append(
            f"- [ ] {idx}.{idx} {it.get('title')} — {it.get('file')}:{it.get('line')}"
        )
        lines.append("")
        lines.extend(_problem_lines(it))
    lines.append("")
    return "\n".join(lines)


def _lint_draft(draft_dir_: Path, project_root) -> List[str]:
    """对草稿目录执行与 daemon 晋升同源的 lint 预检（复用 evolution 形态）。

    ``sys.path`` 指向项目 ``.fenix/`` 后调用 ``core.deliverables.lint_declared``
    与 ``core.deliverables.lint_tasks_parseable``（MUST NOT 自实现第二套）。
    """
    proot = Path(project_root)
    fenix_dir = proot / ".fenix"
    if str(fenix_dir) not in sys.path:
        sys.path.insert(0, str(fenix_dir))
    from core.deliverables import lint_declared, lint_tasks_parseable

    violations: List[str] = []
    for fn in (lint_declared, lint_tasks_parseable):
        try:
            violations.extend(fn(draft_dir_, proot) or [])
        except Exception as e:
            _logger.warning("code_review: 草稿 lint 异常（非阻塞放行）: %s", e)
    return violations


def _git_commit(project_root, draft_copy: Path, spec_name: str) -> Tuple[bool, str]:
    """仅 add 目标 spec 目录后提交（MUST NOT ``git add -A`` / ``git add .``）。

    Returns: ``(ok, error)``；ok=False 时调用方负责清理未跟踪副本。
    """
    git = ["git", "-C", str(project_root)]
    try:
        add = subprocess.run(
            git + ["add", "--", f"spec/changes/{spec_name}"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"git add 失败: {e}"
    if add.returncode != 0:
        return False, f"git add 失败: {add.stderr.strip()[:300]}"
    try:
        commit = subprocess.run(
            git + ["commit", "-m", f"[fenix] spec: {spec_name}"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"git commit 失败: {e}"
    if commit.returncode != 0:
        return False, f"git commit 失败: {commit.stderr.strip()[:300]}"
    return True, ""
