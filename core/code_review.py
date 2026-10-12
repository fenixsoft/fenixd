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
  evo-add-review-night-defer-snapshot-writeoff 3.2 起全仓收集的 scheduled
  （window_start=None，scope=full 周期审查档）同样具备核销资格（解锁仍由
  覆盖完整性守卫把关）；
- 并发写复用 evolution 的 flock + 原子替换形态（_with_lock/_atomic_write）。

日志通道（code-review item 87d7bf7e7ba4）：本模块运维告警（分片目录列举
失败、疑似错名分片点名、items.jsonl 损坏跳过、STATE 判重读取失败、
code_review_state.json 写入失败）走裸 ``logging.getLogger("fenixd.code_review")``。
多项目同进程下该裸子日志器无自有 handler，记录按传播语义串写进最后构造
实例项目的 fenixd.log，生效级别随最后实例的 _level 漂移（core/logger.py
明示的 last-wins 局限，item 9ed664019b2d）——跨项目排障时知悉这些记录
可能落错项目的日志文件。
"""

import fcntl
import hashlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.timelib import now_local, parse_ts

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


def shard_paths(project_root, run_id: str) -> List[Path]:
    """某次 review run 的全部分片产物（``out-<run_id>-b<N>.jsonl``，N 数值升序）。

    分片发现唯一入口（add-code-review-sharded-out D1）：进度读侧、收尾
    ingest、产物硬门三消费侧 MUST 全部经本函数取分片集合，禁止任何一侧
    自写 glob——三处口径漂移是本仓高频事故模式。非 ``-b<正整数>`` 后缀的
    同形文件（如 ``-babc`` / 目录）MUST NOT 被消费。
    """
    d = code_review_dir(project_root)
    prefix = f"out-{run_id}-b"
    found: List[Tuple[int, Path]] = []
    try:
        for p in d.iterdir():
            name = p.name
            if not name.startswith(prefix) or not name.endswith(".jsonl"):
                continue
            n_str = name[len(prefix) : -len(".jsonl")]
            if not re.fullmatch(r"[0-9]+", n_str):
                continue
            n = int(n_str)
            if n < 1 or not p.is_file():
                continue
            found.append((n, p))
    except OSError as e:
        _logger.warning("code_review: 分片目录 %s 列举失败（按无分片处理）: %s", d, e)
        return []
    found.sort(key=lambda t: t[0])
    # 错名分片探测（2026-09-24 事故防线）：agent 曾把分片名截成
    # ``out-<epoch>-b<N>.jsonl``（缺 ``code-review-`` 段），三消费侧全盲。
    # run_id 去掉已知前缀后的同素材错名文件存在时 WARNING 点名——只告警
    # 不消费（读侧口径 fail-显式不 fail-静默，也不放宽 glob 兜错名）。
    # glob 列举全部批次候选（-b2/-b3 等错名分片同样点名），排除与正名
    # ``out-<run_id>-b<N>.jsonl`` 同形的路径（rest 退化拼出正名不误报）。
    rest = run_id[len("code-review-"):] if run_id.startswith("code-review-") else ""
    if rest:
        try:
            legit_re = re.compile(re.escape(f"out-{run_id}-b") + r"[0-9]+\.jsonl")
            strays = sorted(
                p
                for p in d.glob(f"out-{rest}-b*.jsonl")
                if p.is_file() and not legit_re.fullmatch(p.name)
            )
            for stray in strays:
                _logger.warning(
                    "code_review: 疑似错名分片 %s（run %s 的分片名应为 "
                    "out-%s-b<N>.jsonl）——该文件不参与聚合消费，请核对"
                    "落盘方使用的 run_id 是否被截断",
                    stray.name,
                    run_id,
                    run_id,
                )
        except OSError:
            pass
    return [p for _, p in found]


def read_review_out_rows(project_root, run_id: str, on_error=None) -> List[dict]:
    """聚合读取某次 review run 的全部产物行（add-code-review-sharded-out D2）。

    迭代顺序：分片（``shard_paths`` N 升序）→ 主产物 ``out-<run_id>.jsonl``。
    逐行 json.loads，空行/不可解析行/非 dict 行过滤；同 ``file`` 多行保留
    **先见者**（分片是原始产出，主产物是汇总兜底——提示词已约束主 agent
    不重写分片批次，去重是机械兜底）。三消费侧（read_progress / 收尾
    ingest / 产物硬门）MUST 统一经本函数取行，禁止自写读取口径。

    ``on_error(source, exc)``：某来源（分片或主产物）读取发生 OSError 时
    回调注明并跳过该来源——单分片失败不中断整轮；不传则静默跳过。文件
    缺失（如分片直写模式下主产物尚未创建）是常态而非错误，不回调。各
    消费侧更严的有效性判据（如 ingest/硬门要求 ``findings`` 为列表）由
    消费侧在返回行上自行过滤。
    """
    rows: List[dict] = []
    seen_files: set = set()
    for src in [*shard_paths(project_root, run_id), out_path(project_root, run_id)]:
        if not src.is_file():
            continue
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            if on_error is not None:
                try:
                    on_error(src, e)
                except Exception:  # noqa: BLE001 — 回调异常不影响读取主流程
                    pass
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            file_ = str(rec.get("file") or "")
            if not file_ or file_ in seen_files:
                continue
            seen_files.add(file_)
            rows.append(rec)
    return rows


# ── 分片续跑：覆盖/剩余清单计算（evo-add-code-review-ratelimit-resume 3.1）──
# 事故基线（code-review-1790574672）：218 轮全仓审查死于账户级 429，自述 16
# 分片仅落 4 片；既有重派消费复用原 manifest 全量重跑（270 文件级，重烧约 14
# 美元），而分片行 file 字段与 manifest 清单足以算出剩余文件。本组纯函数只判
# 不派：剃余决策在 admin_monitor._consume_ratelimit_redispatch（消费侧回调），
# 核销解锁判定在 maintenance_runs.run_code_review 收尾分支。


def read_manifest_files(project_root, run_id: str) -> List[str]:
    """读取某次 review run 的 manifest 文件清单（派发时落盘，total 权威来源）。

    返回 ``files`` 字符串列表；manifest 缺失/损坏/字段非列表回退 ``[]``——
    调用方对空清单按「完整性不可判」处理（核销守卫维持抢救红线）。
    """
    data = _read_json_file(manifest_path(project_root, run_id))
    files = data.get("files")
    if not isinstance(files, list):
        return []
    return [str(f) for f in files if str(f)]


def covered_files(project_root, run_id: str) -> set:
    """某次 review run 已落账产物覆盖的文件集合（聚合口径：分片 + 主产物）。

    覆盖判定以聚合读侧行的 ``file`` 字段为准（agent 逐文件追加一行——
    含零发现文件，提示词已约束），与 read_progress 的 done 计数同源。
    产物全缺失（run 早夭零分片）→ 空集。
    """
    covered: set = set()
    for rec in read_review_out_rows(project_root, run_id):
        file_ = str(rec.get("file") or "")
        if file_:
            covered.add(file_)
    return covered


def redispatch_chain_run_ids(project_root, run_id: str) -> List[str]:
    """某次 review run 及其全部 429 重派后代（按 manifest ``redispatch_of``
    链路，先根后链，拓扑序）。

    全量扫描 code-review 暂存区的 manifest-*.json 建 ``run_id → redispatch_of``
    映射后回溯——manifest 派发时落盘且重派链路只增不改，扫描即权威。损坏/
    缺字段的 manifest 按「非重派」处理（不入链）；环防御：已入链 run 不重复
    展开（上限 1 的生产链长 ≤2，防御性容忍任意深度）。
    """
    of_map: Dict[str, str] = {}
    d = code_review_dir(project_root)
    try:
        candidates = list(d.glob("manifest-*.json"))
    except OSError:
        candidates = []
    for p in candidates:
        rid = p.name[len("manifest-"):-len(".json")]
        if not rid:
            continue
        parent = _read_json_file(p).get("redispatch_of")
        if isinstance(parent, str) and parent:
            of_map[rid] = parent
    chain = [run_id]
    # 广度优先展开后代：每个 rid 的直接子代 = of_map 中父指向 rid 的键
    frontier = [run_id]
    while frontier:
        parent = frontier.pop(0)
        children = sorted(rid for rid, of in of_map.items() if of == parent)
        for child in children:
            if child not in chain:  # 环防御
                chain.append(child)
                frontier.append(child)
    return chain


def cumulative_covered_files(project_root, run_id: str) -> set:
    """某次 review run 及其重派链的**累计覆盖**文件集合（task 3.2 核销解锁门
    与重派剃余共用的同一口径）。

    覆盖 = 链上每个 run（原 run + 全部重派后代）各自落账产物的 file 字段
    并集。「本轮累计覆盖 = 完整 manifest」之前 MUST NOT 触发全仓快照核销。
    """
    covered: set = set()
    for rid in redispatch_chain_run_ids(project_root, run_id):
        covered |= covered_files(project_root, rid)
    return covered


def remaining_manifest(manifest, covered: set) -> List[str]:
    """原清单 − 已覆盖 = 剩余待审清单（task 3.1）。

    保持原清单顺序并按原清单去重（重派 manifest 是原 manifest 的子序列，
    剃余只删不改序）；covered 中的文件剔除，其余原样保留。
    """
    covered_norm = {str(f) for f in covered}
    out: List[str] = []
    seen: set = set()
    for f in manifest:
        fs = str(f)
        if fs in covered_norm or fs in seen:
            continue
        seen.add(fs)
        out.append(fs)
    return out


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


def _read_items_unlocked(
    path: Path,
    corrupted_out: Optional[List[str]] = None,
    degraded_out: Optional[List[bool]] = None,
) -> Dict[str, dict]:
    """锁内使用的 items.jsonl 读取（等价 read_items 但路径直传、不加锁）。

    解析口径单源：read_items 直接复用本实现（code-review item 07bedf124a12，
    原先两份逐字实现已漂移——锁内 OSError 静默、锁外记 WARNING）。容错与
    read_items 同款：文件缺失按空集，OSError / 单行 JSON 损坏记 WARNING 后
    降级，MUST NOT 让整个读取失败。MUST NOT 在此再加锁（_with_lock 契约
    禁止在 fn 内重入同一把锁）。

    可区分失败信号（code-review item 9a358bba128c）：返回值容错形态不变
    （未感知降级的既有调用方零改动），降级细节经可选出参回传——
    - ``degraded_out``：传列表则 OSError 读失败时置 ``[True]``。全量替换
      写侧 MUST 据此拒绝本次落盘（瞬时读故障窗口内的全量替换会把台账
      整体清空）；读侧容错契约不受影响。
    - ``corrupted_out``：传列表则无法入账行的原始文本原样收集（JSON 损坏
      行，及解析成功但顶层非 dict / item_id 缺失或非字符串的行），回写侧
      MUST 追加回写保留现场，而非静默丢弃。
    """
    out: Dict[str, dict] = {}
    if not path.is_file():
        return out
    try:
        # errors="replace"：坏 UTF-8 字节降级为替换符，由后续逐行 JSON 解析自然
        # 兜底——否则 UnicodeDecodeError 会从全部读写路径穿透（同
        # read_review_out_rows 的读取口径）
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        _logger.warning("code_review: 读取 items.jsonl 失败: %s", e)
        if degraded_out is not None:
            degraded_out.append(True)
        return out
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            _logger.warning("code_review: items.jsonl 第 %s 行 JSON 损坏已跳过: %s", lineno, e)
            if corrupted_out is not None:
                corrupted_out.append(line)
            continue
        if isinstance(rec, dict) and isinstance(rec.get("item_id"), str):
            out[rec["item_id"]] = rec
        else:
            # 解析成功但无法入账（顶层非 dict / item_id 缺失或非字符串，如
            # 手工编辑混入的 {} 或 {"item_id": 123}）：与 JSON 损坏行同款
            # 待遇——记 WARNING 留痕 + 原样收进 corrupted_out 由回写侧追加
            # 回写保留。否则下次全量重写（_mutate_items_unlocked）即被静默
            # 清除，同为无法识别的台账内容一类留痕保留、一类无痕消失，台账
            # 内容丢失无从排查（code-review item 1e954a7a38ec，对齐
            # 9a358bba128c 的不静默丢弃契约）。
            _logger.warning(
                "code_review: items.jsonl 第 %s 行 JSON 可解析但无法入账"
                "（顶层非 dict 或 item_id 缺失/非字符串）已跳过: %.200s",
                lineno,
                line,
            )
            if corrupted_out is not None:
                corrupted_out.append(line)
    return out


def read_items(project_root) -> Dict[str, dict]:
    """读取 ``.fenix/code-review/items.jsonl``，按 item_id 建索引返回 dict。

    文件不存在按空集合处理；单行 JSON 损坏记 WARNING 后跳过（MUST NOT 让
    整个读取失败——dashboard 列表端点依赖此容错）。解析复用
    _read_items_unlocked（本函数本身无锁，直接走其不加锁实现，code-review
    item 07bedf124a12）。
    """
    return _read_items_unlocked(items_path(project_root))


def write_items(project_root, records) -> None:
    """全量写回 items.jsonl（读-改-写 + flock + 原子替换展开见 upsert_findings）。

    每条一行 JSON；调用方传入 ``records`` 兼容两种入参（docstring 既有契约）：
    - ``item_id → 记录 dict`` 的映射（直接取 .values()）；
    - 可迭代的记录序列。
    旧实现只按可迭代处理：真传入 dict 时迭代得到字符串键、全部被 continue
    跳过，最终 ``content = ""`` 会把台账整体清空——一次静默的全量丢失
    （code-review item f81b36084781）。此处入口统一归一化。
    同一 item_id MUST 只保留一条（dict 天然保证）。

    无生产调用方，仅供测试夹具使用；全量替换绕过读降级（degraded）/
    损坏行保留（corrupted）契约，调用方须自证整份记录完整后再落盘。
    """
    if isinstance(records, dict):
        records = list(records.values())
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


def _mutate_items_unlocked(
    path: Path,
    mutator,
    *,
    degraded_note: Optional[str] = None,
    strict_degraded: bool = False,
) -> None:
    """锁内使用的 items.jsonl 读-改-写单源（六处写路径共用样板）。

    upsert_findings / resolve_snapshot / set_item_status / _mark_in_spec /
    mark_resolved / mark_ignored 的同构闭包（锁内读取 → 守卫过滤 → sorted
    回写损坏行 → _atomic_write）收敛于此：``mutator(current) -> bool`` 对
    ``item_id → 记录 dict`` 原地施展各自的守卫过滤逻辑，返回是否需要落盘
    （False 即零命中不重写，对齐 9ec5d0c097ca 的 changed 短路）；True 则
    sorted 序列化 + JSON 损坏行原样回写保留（9a358bba128c：不静默丢弃）+
    原子替换。

    读降级（OSError 类）口径按各写路径既有行为逐路复刻、不借机统一：
    - ``strict_degraded=True``（须与 ``degraded_note`` 同传）：记 WARNING 后
      上抛 ``OSError``（_mark_in_spec 专属——SPEC 此刻已提交并注册，静默
      跳过会让 generate_fix_spec 误判置位成功、条目留在 open 下轮重复立项，
      8e0e362859de；上抛复用其置位写失败错误通道）；
    - 仅传 ``degraded_note``：记 WARNING（含该后缀文案）后拒绝本次全量替换
      保持台账原样（9a358bba128c——瞬时读故障窗口内的全量替换会把台账整体
      清空），mutator 不执行；
    - 二者皆缺省：不单独处置，降级读得空集后 mutator 照常执行
      （resolve_snapshot 靠零变更短路、set_item_status 走「条目不存在」，
      均为既有天然 no-op 口径）。

    MUST NOT 在此再加锁（_with_lock 契约禁止在 fn 内重入同一把锁）。
    """
    corrupted: List[str] = []
    read_degraded: List[bool] = []
    current = _read_items_unlocked(path, corrupted_out=corrupted, degraded_out=read_degraded)
    if read_degraded:
        if strict_degraded:
            _logger.warning("code_review: items.jsonl 读取降级，%s", degraded_note)
            raise OSError(f"items.jsonl 读取降级，{degraded_note}（{path}）")
        if degraded_note is not None:
            _logger.warning("code_review: items.jsonl 读取降级，%s", degraded_note)
            return
    if not mutator(current):
        return
    content = "".join(json.dumps(current[k], ensure_ascii=False) + "\n" for k in sorted(current))
    # JSON 损坏行原样回写保留（code-review item 9a358bba128c：不静默丢弃）
    content += "".join(raw + "\n" for raw in corrupted)
    _atomic_write(path, content)


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


# severity 归一映射（2026-09-23 根治漂移）：契约四档 critical|major|minor|info
# （agents/code-review.md「严重度定义」），但第一步 ocr scan 产出自带
# high/medium/low 值域，经 agent「原样透传」落台账（归一责任在 agent、写侧
# 此前无校验，实测漂移 80/543 条）。口径与 dashboard/data/artifacts.py 的
# verify-bugs 归一一致：high/medium→major、low→minor。severity 不参与
# fingerprint，归一不影响条目去重。
_SEVERITY_NORMALIZE = {
    "critical": "critical",
    "high": "major",
    "major": "major",
    "medium": "major",
    "minor": "minor",
    "low": "minor",
    "info": "info",
}


def normalize_severity(value) -> str:
    """severity 归一：漂移值域 high/medium/low 映射回契约四档。

    空/缺失回 info（与原 ``or "info"`` 缺省同语义）；表内命中归一；未知值
    原样透传（fail-open，同 artifacts.py 先例——读侧/前端有兜底排序与色系）。
    """
    raw = str(value or "info")
    return _SEVERITY_NORMALIZE.get(raw, raw)


# ── severity 分级门限（evo-add-codefix-severity-batch-gate）────────────
#
# 谓词单一函数供给 code_review.generate_fix_spec（候选层）与
# code_fix.select_batch / checkpoint（选批层）两处导入，避免规则漂移
# （design §3「双入口同门」）。门限比较按档位序 info < minor < major <
# critical；regression- 前缀条目（回归来源）豁免门限，保持既有当日重修
# 语义；code-review 来源未知档位按低于门限处理（fail-open 挂起而非误修）。

SEVERITY_GATE_MIN_DEFAULT = "major"
MINOR_BATCH_CADENCE_DEFAULT = 7

# 挂起标记字段名（evo-add-codefix-severity-batch-gate 2.1）：与既有
# WIP-defer 延迟合回台账（core/code_fix.py fix-deferred.json /
# _deferred_item_ids / first_deferred_at）显式区分——两机制不共载体、
# 不共放行判据（spec「deferred 与链收敛对账」Requirement）。
SEVERITY_DEFERRED_FIELD = "severity_deferred"
SEVERITY_DEFERRED_SINCE_FIELD = "severity_deferred_since"

# 档位序（低 → 高）：周批窗口与门限比较共用同一排序基准
_SEVERITY_GATE_TIERS = ("info", "minor", "major", "critical")
_SEVERITY_GATE_RANK = {tier: rank for rank, tier in enumerate(_SEVERITY_GATE_TIERS)}

# 周批窗口换算基数（秒/天）
_SEVERITY_GATE_DAY_SECONDS = 86400


def severity_gate_rank(value) -> int:
    """severity 档位序：info(0) < minor(1) < major(2) < critical(3)。

    未知/缺失档位回 -1（低于任何门限）：词表硬编码 severity 的评审来源
    若未来出现新档位，须显式映射后才能进入选批（design §5）；缺失档位同
    口径处理（写侧 upsert_findings 经 normalize_severity 恒产词表值，缺失
    只可能来自外部直写的台账记录）。
    """
    return _SEVERITY_GATE_RANK.get(str(value or ""), -1)


def is_regression_finding(rec) -> bool:
    """regression- 前缀条目判别：回归来源豁免 severity 门限。

    回归复发（add-regression-auto-fix）保持既有当日重修语义，不参与
    minor/info 延后累积；「未知档位按低于门限」规则亦不作用于本来源
    （其 severity 为 high/medium/low 值域，design §2）。
    """
    return str((rec or {}).get("category") or "").startswith("regression-")


def severity_meets_gate(rec, gate) -> bool:
    """达门限判别（不含周批窗口）：regression- 豁免恒真。

    severity 档位序达到 ``min_immediate_severity`` 即为真；未知/缺失档位
    （rank -1）低于任何门限恒假（fail-open 挂起）。
    """
    if is_regression_finding(rec):
        return True
    min_sev = (gate or {}).get("min_immediate_severity") or SEVERITY_GATE_MIN_DEFAULT
    return severity_gate_rank((rec or {}).get("severity")) >= severity_gate_rank(min_sev)


def severity_gate_from_config_segment(seg) -> Optional[dict]:
    """从 ``get_code_review_fix_config`` 段读取器输出取门限生效值。

    段读取器已做词表/正整数校验回退（core/config.py 1.1），此处对「测试
    替身 config 段未走读取器」的形态做同款兜底归一；checkpoint 选批与
    severity_gate_config（磁盘解析路径）共用本归一，避免双处漂移。

    总开关（2026-10-11）：``severity_batch_gate_enabled`` 缺省关闭——
    关闭时返回 ``None``（门限/周批整体旁路，当天发现的所有内容当天
    处理）；仅显式 ``True`` 时返回门限 dict。非 bool 值视同关闭（与
    读取器严格 bool 口径一致，测试替身段兜底）。
    """
    segd = seg or {}
    enabled = segd.get("severity_batch_gate_enabled", False)
    if not isinstance(enabled, bool):
        enabled = False
    if not enabled:
        return None
    min_sev = segd.get("min_immediate_severity")
    if not (isinstance(min_sev, str) and min_sev in _SEVERITY_GATE_RANK):
        min_sev = SEVERITY_GATE_MIN_DEFAULT
    cadence = segd.get("minor_batch_cadence")
    if (
        not isinstance(cadence, int)
        or isinstance(cadence, bool)
        or cadence <= 0
    ):
        cadence = MINOR_BATCH_CADENCE_DEFAULT
    return {"min_immediate_severity": min_sev, "minor_batch_cadence": cadence}


def severity_gate_config(project_root) -> Optional[dict]:
    """解析 severity 门限生效值（模块级调用方路径，磁盘配置 fail-open）。

    沿 ``_stall_alert_minutes`` 同款范式：配置层任何异常回退缺省，不中断
    评审与修复主链。总开关关闭（缺省）时返回 ``None``＝门限旁路
    （severity_gate_from_config_segment 2026-10-11 缺省翻转）。
    """
    try:
        from core.config import ConfigLoader

        seg = ConfigLoader.get_code_review_fix_config(
            ConfigLoader.resolve_config(project_root)
        )
    except Exception:  # noqa: BLE001 — 配置层任何异常回退缺省
        seg = {}
    return severity_gate_from_config_segment(seg)


def _parse_gate_ts(value) -> Optional[float]:
    """挂起时间锚解析（epoch 秒）：ISO8601；解析失败回 None（窗口按未到）。

    走 timelib.parse_ts 唯一解析入口（naive 串按本地时区解读——全仓唯一
    策略；本模块挂起锚写入侧经 to_storage 落 Z 后缀 aware 串，不受影响）。
    """
    dt = parse_ts(str(value))
    if dt is None:
        return None
    return dt.timestamp()


def severity_gate_open(rec, gate=None, now_ts=None, release_due=False) -> bool:
    """severity 谓词（单一函数）：条目当前是否可进当日修复批。

    - regression- 前缀条目豁免门限（恒可进当日批）；
    - severity 达 ``min_immediate_severity``：当日批；
    - 低于门限：挂起，距挂起锚（``severity_deferred_since``，缺位回退
      ``first_seen_at``——存量条目零回填）达 ``minor_batch_cadence`` 天的
      周批窗口时放行；``release_due=True``（组放行窗口到期，由
      ``severity_gate_release_due`` 判定）时低于门限条目整组放行。

    ``gate`` 为 ``None``（总开关关闭，2026-10-11）：恒 True＝全放行
    当日批（无门限即无挂起）。
    """
    if gate is None:
        return True
    if severity_meets_gate(rec, gate):
        return True
    if release_due:
        return True
    cadence = (gate or {}).get("minor_batch_cadence")
    if not isinstance(cadence, int) or isinstance(cadence, bool) or cadence <= 0:
        cadence = MINOR_BATCH_CADENCE_DEFAULT
    anchor = _parse_gate_ts(
        (rec or {}).get(SEVERITY_DEFERRED_SINCE_FIELD)
        or (rec or {}).get("first_seen_at")
    )
    if anchor is None:
        return False
    if now_ts is None:
        now_ts = datetime.now(timezone.utc).timestamp()
    return (now_ts - anchor) >= cadence * _SEVERITY_GATE_DAY_SECONDS


def severity_gate_release_due(recs, gate=None, now_ts=None) -> bool:
    """周批组放行窗口判定：挂起集中最早锚距今达 ``minor_batch_cadence`` 天。

    「整组放行」（design §2）：窗口到期时累积的全部低于门限条目一并进入
    当批（非逐条到期逐条放行）。锚取每条 ``severity_deferred_since``（缺位
    回退 ``first_seen_at``）的最早值；达门限/豁免条目不参与挂起组。挂起集
    为空或锚均不可解析 → False（窗口未到）。

    ``gate`` 为 ``None``（总开关关闭）：恒 False＝无挂起组（窗口恒未到）。
    ``recs`` 由调用方限定 open 池（resolved/ignored 条目的残留老锚
    MUST NOT 参与窗口判定——2026-10-11 口径修复，与 select_batch 同池）。
    """
    if gate is None:
        return False
    cadence = (gate or {}).get("minor_batch_cadence")
    if not isinstance(cadence, int) or isinstance(cadence, bool) or cadence <= 0:
        cadence = MINOR_BATCH_CADENCE_DEFAULT
    earliest = None
    for rec in recs or ():
        if not isinstance(rec, dict) or severity_meets_gate(rec, gate):
            continue
        anchor = _parse_gate_ts(
            rec.get(SEVERITY_DEFERRED_SINCE_FIELD) or rec.get("first_seen_at")
        )
        if anchor is not None and (earliest is None or anchor < earliest):
            earliest = anchor
    if earliest is None:
        return False
    if now_ts is None:
        now_ts = datetime.now(timezone.utc).timestamp()
    return (now_ts - earliest) >= cadence * _SEVERITY_GATE_DAY_SECONDS


def apply_severity_gate_marker(rec, gate) -> bool:
    """按门限维护条目挂起标记（原位改写，返回是否有改动；落盘由调用方
    在既有读-改-写锁内完成）。

    - 达门限 / regression- 豁免：清挂起标记——重复发现把 severity 刷到
      达门限档位时按当日批处置并清除挂起标记（design §2）；
    - 低于门限：置标记；``severity_deferred_since`` 保留首个锚（同指纹
      重复发现刷新展示字段时不重置，周批窗口以首挂起时刻起算）。

    ``gate`` 为 ``None``（总开关关闭，2026-10-11）：不改标记返回 False
    （挂起标记留存量无害——读侧 ``gate`` 关闭时不消费；重开开关时周批
    窗口仍以首挂起锚起算）。
    """
    if gate is None:
        return False
    if severity_meets_gate(rec, gate):
        if rec.get(SEVERITY_DEFERRED_FIELD) is None and rec.get(
            SEVERITY_DEFERRED_SINCE_FIELD
        ) is None:
            return False
        rec.pop(SEVERITY_DEFERRED_FIELD, None)
        rec.pop(SEVERITY_DEFERRED_SINCE_FIELD, None)
        return True
    sev = str(rec.get("severity") or "")
    if sev and sev not in _SEVERITY_NORMALIZE:
        # 未知档位告警（design §5）：fail-open 挂起而非误修
        _logger.warning(
            "code_review: 条目 %s severity %r 非 severity 词表值，"
            "按低于门限挂起（周批窗口后放行）",
            rec.get("item_id"),
            sev,
        )
    changed = False
    if rec.get(SEVERITY_DEFERRED_FIELD) is None:
        rec[SEVERITY_DEFERRED_FIELD] = True
        changed = True
    if rec.get(SEVERITY_DEFERRED_SINCE_FIELD) is None:
        rec[SEVERITY_DEFERRED_SINCE_FIELD] = _now_iso()
        changed = True
    return changed


def severity_deferred_open_ids(project_root, gate=None, now_ts=None,
                               exclude_ids=None) -> set:
    """open 且低于门限且未到周批窗口的条目 id 集（链收敛对账的挂起集）。

    组放行窗口到期时挂起集为空（整组已可进批，选批层将自然放行）。
    台账读失败按空集 fail-open（对账面只影响收敛文案分级，不影响选批）。

    口径（2026-10-11 误报修复）：与 ``select_batch`` 同池判定——池限定
    open 条目并排除 ``exclude_ids``（调用方传链内跳过集/失败档案并集，
    与选批排除同口径）；组放行窗口基于同池计算。resolved/ignored 条目的
    残留挂起锚 MUST NOT 参与窗口判定（曾令 release_due 误判到期 → 挂起
    集恒空 → blocked 误落 failed_batch_retained「链内跳过/预算内失败」
    文案而非 severity_deferred 健康等待态）。

    ``gate`` 为 ``None``（总开关关闭）：恒空集（无门限无挂起）。
    """
    g = gate if gate is not None else severity_gate_config(project_root)
    if g is None:
        return set()
    try:
        items = read_items(project_root)
    except Exception:  # noqa: BLE001 — 读失败按空集（不误判收敛语义）
        return set()
    excluded = set(str(i) for i in (exclude_ids or ()))
    pool = [
        rec
        for rec in items.values()
        if isinstance(rec, dict)
        and rec.get("status") == "open"
        and str(rec.get("item_id")) not in excluded
    ]
    release = severity_gate_release_due(pool, g, now_ts=now_ts)
    return {
        str(rec.get("item_id"))
        for rec in pool
        if not severity_gate_open(rec, g, now_ts=now_ts, release_due=release)
    }


def _item_id(project: str, file: str, fp: str) -> str:
    """条目稳定 id：``sha1(project|file|fingerprint)[:12]``。

    同一问题重复观测不变（同一项目/文件/指纹 → 同 id）。
    """
    return hashlib.sha1(f"{project}|{file}|{fp}".encode("utf-8")).hexdigest()[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_line(value) -> int:
    """把 LLM/ocr 产出的 ``line`` 字段容错归一为 int。

    agent 常写出非纯数字形态（``"12-15"`` / ``"L12"`` / ``"N/A"`` / 浮点串），
    直接 ``int()`` 会抛 ValueError/TypeError 并穿透 ``_with_lock``，使整轮落账
    被判失败（code-review item 26cc257399e7 / 9e4636798ccd）——与本函数「缺
    关键字段的发现跳过，不整批失败」的取向相悖。容错策略：先试 int，失败则
    用正则提取首个整数段，仍无则回退 1（行号仅用于排序展示，非事实字段）。
    """
    if value is None or value == "":
        return 1
    if isinstance(value, bool):
        return 1
    if isinstance(value, int):
        # 负数/0 与缺省回退同基准钳到 ≥1（与字符串分支口径对齐）
        return max(value, 1)
    if isinstance(value, float):
        # NaN/inf 截断为 int 会抛 ValueError/OverflowError（前置的 None/空串/
        # bool/int 条件均不覆盖），显式先行回退 1（value != value 仅 NaN 为
        # 真）；其余截断结果与 int 分支同口径钳到 ≥1
        #（0.9 → 1、-3.5 → 1，避免落账出 0/负行号）
        if value != value or math.isinf(value):
            return 1
        return max(int(value), 1)
    m = re.search(r"\d+", str(value))
    if m:
        try:
            return int(m.group(0))
        except ValueError:
            return 1
    return 1


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

    去重语义：同 fingerprint 已存在 → 刷新除 status / spec_name /
    first_seen_at 外的全部展示字段（file / line / severity / category /
    title / description / suggestion / evidence / last_seen_at / review_id /
    review_kind / reviewed_at；spec_name 仅原值为空且本轮有关联时补写）；
    不存在 → 插入新条目（status=open，first_seen_at == last_seen_at == now）。

    Returns: ``{"inserted": n, "updated": n}``
    """
    spec_map = spec_map or {}
    now = _now_iso()
    project = str(Path(project_root).name) or str(project_root)
    path = items_path(project_root)
    inserted = 0
    updated = 0
    # severity 门限生效值（evo-add-codefix-severity-batch-gate 2.1）：锁外
    # 解析（磁盘配置读取不进 flock 临界区）。挂起标记随落账维护——低于
    # 门限条目首次观测即带挂起锚（首个 severity_deferred_since），选批/
    # 候选两层凭同一谓词判周批窗口；severity 刷到达门限档位时清标记
    # （升档晋级按当日批处置）。
    gate = severity_gate_config(project_root)

    def _apply(current: Dict[str, dict]) -> bool:
        nonlocal inserted, updated
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
                "line": _coerce_line(finding.get("line")),
                "severity": normalize_severity(finding.get("severity")),
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
                apply_severity_gate_marker(rec, gate)
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
                # 挂起标记随 severity 刷新维护（evo-add-codefix-severity-
                # batch-gate）：升档清标记晋级当日批、持续低于门限保留首个
                # 锚（同指纹合并沿既有分支，不新增立项路径）
                apply_severity_gate_marker(rec, gate)
                updated += 1
        # upsert 语义即全量重写（无零变更短路）：空 findings 也按现序重排落盘
        return True

    # 读降级拒写（code-review item 9a358bba128c）：台账完整性未知，拒绝本次
    # 全量替换保持台账原样——瞬时读故障窗口内的全量替换会把既有条目整体清掉
    _with_lock(path, lambda: _mutate_items_unlocked(path, _apply, degraded_note="本轮审查发现跳过落账"))
    return {"inserted": inserted, "updated": updated}


def resolve_snapshot(project_root, observed_fingerprints: set, now: Optional[str] = None) -> int:
    """全仓快照核销：open 且本轮未再观测到的条目置 resolved。

    调用方保证仅在 ``review_kind == "manual_full"`` 或全仓收集的 scheduled
    （window_start=None，evo-add-review-night-defer-snapshot-writeoff 3.2
    放宽）收尾时调用（本函数不做 review_kind 判定，核销资格与覆盖完整性
    职责在 run_code_review 收尾分支）。

    核销语义：台账中 ``status == "open"`` 且 fingerprint 不在
    ``observed_fingerprints`` 中的条目置 ``resolved``（记录 resolved_at）；
    MUST NOT 触碰 ``in_spec`` / ``ignored``（全仓快照核销场景）。

    Returns: 被核销的条目数。
    """
    now = now or _now_iso()
    path = items_path(project_root)
    resolved_count = 0

    def _apply(current: Dict[str, dict]) -> bool:
        nonlocal resolved_count
        changed = False
        for rec in current.values():
            if rec.get("status") != "open":
                continue
            fp = rec.get("fingerprint")
            if isinstance(fp, str) and fp in observed_fingerprints:
                continue
            rec["status"] = "resolved"
            rec["resolved_at"] = now
            # last_seen_at 保持最后观测时刻不动（核销时刻由 resolved_at 承载）
            changed = True
            resolved_count += 1
        return changed

    # 读降级不单独处置（既有口径）：降级读得空集 → 零变更短路天然不落盘
    _with_lock(path, lambda: _mutate_items_unlocked(path, _apply))
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
    result: dict = {}

    def _apply(current: Dict[str, dict]) -> bool:
        rec = current.get(item_id)
        if rec is None:
            result.update({
                "ok": False,
                "item_id": item_id,
                "status": status,
                "error": f"条目不存在: {item_id}",
            })
            return False
        prev = rec.get("status")
        if prev == status:
            # 幂等：重复标记同一状态不报错、无副作用
            result.update({"ok": True, "item_id": item_id, "status": status, "error": None, "idempotent": True})
            return False
        rec["status"] = status
        if status == "open" and prev == "in_spec":
            # 清除归属：in_spec → open 时清空 spec_name
            rec["spec_name"] = None
        if spec_name is not None:
            rec["spec_name"] = spec_name
        result.update({"ok": True, "item_id": item_id, "status": status, "error": None})
        return True

    # 读降级不单独处置（既有口径）：降级读得空集 → 走「条目不存在」错误且不落盘
    _with_lock(path, lambda: _mutate_items_unlocked(path, _apply))
    return result


# ── 周期窗口（与自省同源） ─────────────────────────────────────────


def _read_json_file(path: Path) -> dict:
    """读取 JSON 文件；缺失/损坏返回空 dict。"""
    try:
        # errors="replace"：坏 UTF-8 字节降级为替换符，由后续 json.loads 兜为
        # JSONDecodeError 路径——否则 UnicodeDecodeError 会穿透到进度端点与
        # 周期调度（同 _read_items_unlocked / read_request_result 的容错口径）
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _iso_to_aware_dt(iso_str: Optional[str]) -> Optional[datetime]:
    """ISO 时间戳（含 Z 后缀）→ aware datetime；解析失败返回 None。

    SPEC-B 批④：原 ``_iso_to_local_dt``（aware 转本地后剥时区收尾，窗口
    边界为 naive ``datetime.now()``）随裸 ``now()`` 一起退役——窗口边界改
    aware（``compute_window`` 走 ``timelib.now_local()``），全链不再剥时区，
    aware/naive 混比 TypeError 风险随之消除。解析内核 timelib.parse_ts
    单源（consolidation-layer 4.1 收拢不变）。
    """
    return parse_ts(iso_str)


def compute_window(project_root, now: Optional[datetime] = None) -> Tuple[datetime, str]:
    """周期窗口起点：三态水位（add-code-review-run-at 3.2）。

    优先读 ``.fenix/code_review_state.json`` 的 ``last_run_at``（审查车道
    自身水位——触发时点与自省解耦后，窗口必须跟审查自身节奏，否则审查
    时点晚于自省时窗口被当晨自省覆写、两段审查之间的变更滑出所有窗口，
    静默覆盖缺口）；缺失（首跑/存量状态）回退读
    ``.fenix/self_review_state.json`` 的 ``last_run_at``（＝历史行为逐位
    一致）；再缺失回退 ``now - 24h``。

    ``window_kind`` 二值映射不变：读到任一 ``last_run_at``（审查自身或自省
    回退）返回 ``"last_run"``，双缺失回退 24h 返回 ``"fallback"``（消费方
    日志/审计口径不受三态水位影响）。``window_start`` 为 aware（瞬时与原
    naive 本地一致；时区表述随输入——naive 串按本地、aware 串保留原时区）。
    消费侧 ``collect_manifest`` 的 ``git log --since``（ISO 串带偏移，git
    按偏移解读）与 prompt/元数据 ``isoformat()`` 均瞬时等价。
    """
    now = now or now_local()
    cr_state = _read_json_file(_code_review_state_path(project_root))
    last_run_at = _iso_to_aware_dt(cr_state.get("last_run_at"))
    if last_run_at is not None:
        return last_run_at, "last_run"
    state = _read_json_file(Path(project_root) / ".fenix" / "self_review_state.json")
    last_run_at = _iso_to_aware_dt(state.get("last_run_at"))
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
# 排除规则单一来源（code-review item 3bc2bb0880a3 / 8dc7328123b8）：
# 顶层排除目录同时需要「路径前缀」与「任意层目录名」两种判据，此前
# _EXCLUDED_DIRS / _EXCLUDED_PREFIXES 两处各自列举、需人工同步（漏一处即
# 静默失效）。现由 _EXCLUDED_TOP_DIRS 单表派生两套判据，消除漂移面。
_EXCLUDED_TOP_DIRS = (
    "spec",
    "docs",
    "dist",
    ".fenix",
    ".git",
    # 测试代码不作为审查对象（2026-09-19 用户决策）：审查面对准产品代码。
    # 全仓 474 文件里 tests/ 占 251，且过半是断言细节而非产品逻辑——
    # 逐文件 LLM 审查既稀释了产品代码的注意力预算，也让 manifest 规模失去意义。
    # 测试自身的质量由测试套件自身把关。
    "tests",
    # vendored 第三方目录不作为审查对象（evo-code-review-vendored-scope）：
    # vendored 文件由上游同步流程承接（文件内自带上游同步注释与 fenix-ignore
    # 标注），入审查面只会逐轮全价重审——potplayer-base 的 whirehair.py
    # （thirdparty 下唯一 .py）5 轮被出题 17 item、两轮 fix batch 实测
    # $2.38/$2.03。目录段精确匹配；external 歧义大（仓内自有代码也可能叫
    # external）不收。vendored 内确需审查的文件走上游同步窗口人工触发专项评审。
    "thirdparty",
    "third_party",
    "vendor",
)
# 任意层级的排除目录名（不限于顶层）：顶层表 ∪ 依赖/缓存/归档目录。
# 注：多段路径（如 'static/dist'）不能放入此集合——判定按 ``p.split("/")``
# 的**单段**目录名比较，多段字符串永不相等（旧值的静默失效项，已移除；
# 构建产物由 _EXCLUDED_PREFIXES 的 core/dashboard/static/dist/ 覆盖）。
_EXCLUDED_DIRS = set(_EXCLUDED_TOP_DIRS) | {
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "archive",
}
_EXCLUDED_PREFIXES = tuple(f"{d}/" for d in _EXCLUDED_TOP_DIRS) + (
    "core/dashboard/static/dist/",
)
# 生成物文件名判据（无法靠目录排除的）：``*.gen.css`` 等由构建命令产出
# （如 tailwind.gen.css 由 package.json 的 prebuild 生成），审查它们是
# 对压缩产物做 LLM 审查，无意义且极烧 token（单文件逾 1 万字符）。
_GENERATED_NAME_MARKERS = (".gen.", ".min.")
_GENERATED_SUFFIXES = (".d.ts",)


def _is_source_file(path_str: str) -> bool:
    """判定是否为受控产品源码文件（排除测试/文档/生成物/运行时产物）。

    排除维度：目录前缀（spec/docs/dist/.fenix/tests 与 vendored 第三方目录
    thirdparty/third_party/vendor）、路径中出现的排除目录名、
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
            # 固化解码（对齐 worktree_manager/repair_site.py 惯例）：默认走
            # locale 首选编码 + 严格模式，非 locale 可解码字节的路径/stderr
            # 会抛 UnicodeDecodeError；errors="replace" 保证解码不炸。
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        # ValueError 兜 UnicodeDecodeError（对齐 git_base_branch._git_output），
        # 保证「失败返回空串」降级契约在解码故障下同样闭合，不沿
        # collect_manifest 冒泡中断周期审查的清单收集。
        # code-review item d8eec4681080。
        _logger.warning("code_review: git %s 执行失败: %s", args[0], e)
        return ""
    if proc.returncode != 0:
        # 非零退出码也留痕：git 层故障（非 git 仓库/索引锁/坏对象）表现为
        # 空 manifest，与「窗口内确实没有变更」不可区分，stderr 是唯一线索
        _logger.warning(
            "code_review: git %s 执行失败（退出码 %s）: %s",
            args[0],
            proc.returncode,
            (proc.stderr or "").strip()[:200],
        )
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
        # -z：以 NUL 分隔原样输出路径，不做 core.quotePath 引号转义（默认
        # true 时非 ASCII 文件名以带引号的八进制转义形式输出，与真实文件
        # 系统路径失配被 is_file 剔除，文件被静默排除出全仓清单；含引号或
        # 换行符的文件名同样错位）。code-review item 42577801cdb3。
        raw = _git(project_root, ["ls-files", "-z"])
        # ls-files 列举的是索引条目：工作树中已删除但未 stage 删除的路径
        # 仍会进入全仓清单，按工作树存在性剔除，兑现与下方 window scope
        # 同款「不让审查对已删除文件空转」的排除语义。
        # code-review item 3b306434100d。
        files = [
            line for line in raw.split("\0")
            if line.strip() and (Path(project_root) / line.strip()).is_file()
        ]
    else:
        # 窗口：window_start 之后变更的文件（--since 走本地时间）。
        # 加 --diff-filter=ACMR：排除 D（删除）与其它无内容形态——已删除文件
        # 列入 manifest 会让审查对该文件空转（读不到内容，白烧一轮 token）。
        # code-review item f27271f33580。
        since = window_start.isoformat() if window_start is not None else None
        if since is None:
            return []
        raw = _git(
            project_root,
            [
                "log",
                "--since",
                since,
                "--diff-filter=ACMR",
                "--name-only",
                "--pretty=format:",
                # -z：文件名以 NUL 结尾且原样输出，不做 core.quotePath 引号
                # 转义（默认 true 时非 ASCII 文件名以带引号的八进制转义形式
                # 输出，与真实文件系统路径失配被下方 is_file 二次剔除，文件
                # 被静默排除出窗口清单）。与上方 full scope 同款修复，
                # code-review item 36685afefe53。
                "-z",
            ],
        )
        # -z 下多 commit 边界（--pretty=format: 空输出 + 分隔 NUL）会留出
        # 空段，文件路径不可能为空串，过滤空段即可还原逐文件序列。
        files = [line for line in raw.split("\0") if line.strip()]
        # --diff-filter=ACMR 按单次提交的变更类型过滤，挡不住窗口内先增/改、
        # 随后又删除的路径（A/M 事件仍会把已消失的文件列入清单）。按工作树
        # 存在性二次剔除，兑现上方「不让审查对已删除文件空转」的排除语义。
        files = [f for f in files if (Path(project_root) / f.strip()).is_file()]
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


# ── 手动触发判定结果回链（add-code-review-trigger-ack 1.1） ──────────

# daemon 消费端写回的判定结果文件，与 code_review_request.json 同族：
# dashboard 原子写信号 → daemon 主循环消费 → 判定结果原子写回，
# GET /api/code-review/run-result 只读透传（对齐 code-fix 结果回链先例）。
CODE_REVIEW_REQUEST_RESULT = ".fenix/code_review_request_result.json"

# 缺省态（文件缺失/损坏/非 dict）：全键在场且值为 null——读侧 MUST NOT 抛
# 异常，前端以 requested_at 真值判定「是否已有结果」。
_REQUEST_RESULT_DEFAULT = {
    "requested_at": None,
    "status": None,
    "reason": None,
    "message": None,
    "finished_at": None,
}


def write_request_result(project_root, requested_at, status, reason=None,
                         message=None, logger=None) -> bool:
    """原子写回手动触发判定结果（同目录 tmp + ``os.replace``，design D1）。

    单文件覆盖写、不清理——消费端每消费一条新信号即覆盖旧结果，``requested_at``
    回链保证前端只认本次触发。``finished_at`` 统一为「本条结果写入时刻」（对
    started 即受理时刻；daemon 不在 run 结束时回写，run 终态由 run 文件承载）。

    写失败（OSError，含 payload 序列化抛出的 TypeError/ValueError）仅经
    logger 记日志并返回 False——结果文件写不进属基础设施异常，无更好的
    用户反馈通道，MUST NOT 让调用方控制流因此中断。
    """
    payload = {
        "requested_at": requested_at,
        "status": status,
        "reason": reason,
        "message": message,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    result_path = Path(project_root) / CODE_REVIEW_REQUEST_RESULT
    try:
        # _atomic_write：mkstemp 唯一临时名 + fsync + os.replace，并发写方
        # 不共享固定名 .tmp，杜绝交错覆写（对齐本模块既有原子写模式，
        # 目录创建与残留 tmp 清理由其内部兜底）。code-review item 629d47de2b54。
        _atomic_write(result_path, json.dumps(payload, ensure_ascii=False, indent=2))
        return True
    except (OSError, TypeError, ValueError) as e:
        if logger is not None:
            logger.error("code_review", f"code_review 手动触发结果写入失败: {e}")
        return False


def read_request_result(project_root) -> dict:
    """读手动触发判定结果（缺省态兜底，MUST NOT 抛异常）。

    文件缺失 / JSON 损坏 / 顶层非 dict → 返回缺省态（全 null 形态）；
    合法 dict 原样返回（消费端写什么读什么，不做白名单裁剪——与
    ``core/dashboard/data`` 的 code-fix 结果读封装同口径）。
    """
    path = Path(project_root) / CODE_REVIEW_REQUEST_RESULT
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return dict(_REQUEST_RESULT_DEFAULT)
    return data if isinstance(data, dict) else dict(_REQUEST_RESULT_DEFAULT)


# ── 进度读取（真实进度，D4） ───────────────────────────────────────


def _latest_review_run(project_root) -> Optional[str]:
    """最新一次 review run 的 run_id（按内嵌 epoch 排序），无则 None。

    run_id 形如 ``code-review-<epoch>``，撞名退避时追加 ``-<n>``
    （maintenance_runs._unique_code_review_run_id，如 ``code-review-<epoch>-2``）。
    旧正则要求名字**以** 9~10 位数字结尾，这类带退避后缀的 run 会被跳过，
    使 read_progress 取到更旧的一次 run（total/done 全错、running 恒 false，
    并让 409 重复触发守卫失效）。故匹配「epoch 后可跟多个 -<n> 段」的形态，
    取首个 epoch 段排序（code-review item ab5d3b4c3fa9）。同秒撞名退避
    （手动+同秒周期双触发）会产出 ``code-review-<epoch>`` 与
    ``code-review-<epoch>-<n>`` 两份真实 run 并存，epoch 平局时以名字
    字典序为确定性次键取更大者——退避 run 由 _unique_code_review_run_id
    在基础候选被申领后才生成（创建序更晚），字典序更大即更新，消除对
    glob 目录序的依赖（code-review item f7b084c51199）。
    """
    d = code_review_dir(project_root)
    if not d.is_dir():
        return None
    latest: Optional[str] = None
    latest_key: Optional[tuple] = None
    try:
        for p in d.glob("manifest-*.json"):
            name = p.name[len("manifest-") : -len(".json")]
            m = re.search(r"(\d{9,10})(?:-\d+)*$", name)
            if not m:
                continue
            ts = int(m.group(1))
            key = (ts, name)
            if latest_key is None or key > latest_key:
                latest_key = key
                latest = name
    except OSError:
        pass
    return latest


def read_progress(project_root) -> dict:
    """读取当前 code-review 运行进度。

    Returns: ``{running, review_id, review_kind, total, done, current}``
    - ``done`` = 主产物 + 全部分片（out-<run_id>-b<N>.jsonl）按 ``file`` 去重
      后与 manifest 清单求交的有效行数（add-code-review-sharded-out：分片
      直写模式下进度聚合；空/不可解析行不计，同 file 多行只计一次；清单外
      路径（agent 幻觉产物）不计入，``done <= total`` 恒成立）；
    - ``total`` = 派发时落盘的 manifest-<review_id>.json 长度；
    - ``current`` = 最后落盘来源（mtime 最晚者，主产物或分片）末行的
      ``file``（被审文件路径，非分片文件名）；
    - ``running`` 判定：取最新一个 run（按 review_id 内嵌 epoch 排序），
      仅当该 run 的 ``.fenix/runs/<review_id>.jsonl`` 末行非终态（无
      result/error/interrupted/cancelled 终态行）且产物 mtime 未超既有
      stale 阈值时 ``running=true``；已有终态行或超时即 ``running=false``
      （对齐 core/dashboard/data/runs.py 的 _classify_run/_RUN_STALE_SECONDS
      同款口径）。终态集合取 _RUN_TERMINAL_STATUS_MAP 全量（result/error/
      interrupted/cancelled/frozen-terminated/superseded/gate-blocked）。
    """
    base = {"running": False, "review_id": None, "review_kind": None,
            "total": 0, "done": 0, "current": None}
    run_id = _latest_review_run(project_root)
    if run_id is None:
        return base
    # 读 manifest（total 权威来源；_read_json_file 自身已容错，缺失/损坏回空 dict）
    mpath = manifest_path(project_root, run_id)
    mdata = _read_json_file(mpath)
    files = mdata.get("files") if isinstance(mdata.get("files"), list) else []
    total = len(files)
    review_kind = mdata.get("review_kind")
    # 读产物（done/current：聚合分片 + 主产物；主产物缺失时进度不归零——
    # 只要有分片行，done 即分片去重行数）
    covered = {str(r.get("file") or "") for r in read_review_out_rows(project_root, run_id)}
    covered.discard("")
    # done 与 manifest 清单求交：agent 幻觉写出的清单外路径不计入进度，
    # done <= total 恒成立（清单缺失/损坏 → total=0 → done=0）
    done = len(covered.intersection(files))
    current = None
    sources = [
        p
        for p in [*shard_paths(project_root, run_id), out_path(project_root, run_id)]
        if p.is_file()
    ]
    if sources:
        try:
            # mtime 最晚者；平局（文件系统粒度粗）取规范序后者——
            # （mtime, index）元组比较，index 大者（主产物）胜出
            latest = max(
                enumerate(sources),
                # [fenix-ignore:90542a07fcf4] stat 已处于外层 try/except OSError 覆盖内，并发清理竞态的 FileNotFoundError 被兜底为 current=None，不会沿 read_progress 冒泡致端点 500
                key=lambda t: (t[1].stat().st_mtime, t[0]),
            )[1]
            # 末行只取 current 一项：复用 runs.py 公开 read_run_lines 的 64KB
            # 尾窗 seek（_read_run_tail，fix-dashboard-read-path-performance
            # D3 同款），不再对 latest 整读第二遍——本函数被前端进度轮询与
            # admin_monitor 巡检反复调用，上面 read_review_out_rows 已把分片+
            # 主产物全量读了一遍，mtime 最晚者（往往恰是最大的分片）再逐字
            # 整读第二遍是 O(文件大小) 的热路径读放大（code-review item
            # c5aa4e019015，对齐 529bc6a8edf2 对 runs/<run_id>.jsonl 的同型
            # 收敛）。解析容错口径不变：末行解析失败（JSON 损坏/非 dict，含
            # 尾窗降级包装的无 file 字段 stderr 伪事件）→ current=None。
            tail = _read_run_tail(latest, max_lines=1)
            last = tail[-1] if tail else None
            if isinstance(last, dict):
                # 缺 file（坏行/解析失败行）时置 None，不回退 title——current
                # 语义是被审文件路径（对齐 docstring），title 回退会让前端
                # 把问题标题当文件路径展示（15818a18ec23）
                current = last.get("file") or None
        except OSError:
            current = None
    # running 判定（终态 + stale 阈值，对齐 runs.py 口径）。末行读取复用
    # runs.py 的 64KB 尾窗 seek（_read_run_lines，fix-dashboard-read-path-
    # performance D3 同款）：审查 run 存续期产物含全部编排事件与超长 result
    # 行，可达数十 MB，而本函数被前端进度轮询与 admin_monitor 巡检反复调用，
    # 整读流是 O(文件大小) 的热路径放大（code-review 529bc6a8edf2）。
    running = False
    run_file = Path(project_root) / ".fenix" / "runs" / f"{run_id}.jsonl"
    if run_file.is_file():
        # _read_run_lines 全程容错不抛错（OSError/空文件 → []，损坏行降级
        # stderr 条目），「末行解析失败/空文件 → last_ev=None」容错口径不变
        tail = _read_run_tail(run_file)
        last_ev = tail[-1] if tail else None
        terminal = _terminal_status_map()
        if isinstance(last_ev, dict) and last_ev.get("type") in terminal:
            running = False
        else:
            # 末行非终态 → 看 mtime 是否超 stale 阈值（SPEC-B 批④：
            # now_local().timestamp() 与原 naive now().timestamp() 同一瞬时）
            try:
                age = now_local().timestamp() - run_file.stat().st_mtime
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


def _stall_alert_minutes(project_root) -> int:
    """停滞告警阈值（分钟）：``admin.code_review.stall_alert_minutes``，缺省 15。

    经 ``ConfigLoader.get_code_review_config`` 归一（与 enabled/max_files/scope
    同一单源）；配置缺失/解析失败/值非法（非正整数，含 bool）回退 15——
    巡检路径 MUST NOT 因配置脏值中断（add-code-review-sharded-out 1.3）。
    """
    default = 15
    try:
        from core.config import ConfigLoader

        cfg = ConfigLoader.resolve_config(project_root)
        value = ConfigLoader.get_code_review_config(cfg).get(
            "stall_alert_minutes", default
        )
    except Exception:  # noqa: BLE001 — 配置层任何异常回退缺省，不中断巡检
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return default
    return value


def check_progress_stall(project_root, now: Optional[datetime] = None) -> Optional[dict]:
    """事中零进度停滞检测（add-code-review-sharded-out 1.3/D4）。

    最新 run 聚合口径 ``running=true`` 且 ``done==0`` 且运行时长（自 manifest
    ``requested_at`` 起算）超过 ``_stall_alert_minutes`` 阈值时返回
    ``{"run_id", "minutes"}``，否则 None。由 admin_monitor 周期节拍调用并
    负责落告警（本函数只判不写）；run 终态（``running=false``）短路不再触发。

    ``now`` 参数供测试注入时钟（naive/aware 皆可，按瞬时差计算）；生产路径
    缺省取 ``timelib.now_local()``（aware 本地，SPEC-B 批③收拢）。
    """
    progress = read_progress(project_root)
    if not progress.get("running"):
        return None
    if progress.get("done") != 0:
        return None
    run_id = progress.get("review_id")
    if not run_id:
        return None
    mdata = _read_json_file(manifest_path(project_root, run_id))
    started = _iso_to_aware_dt(mdata.get("requested_at"))
    if started is None:
        return None
    # SPEC-B 批③④：缺省钟与 started 均 aware；时长按 .timestamp() 瞬时差
    # 计算（naive 注入替身按本地解读 .timestamp()，aware 注入直取——皆与
    # 迁移前 naive-naive 减法同一瞬时）。
    now_dt = now if now is not None else now_local()
    minutes = int((now_dt.timestamp() - started.timestamp()) // 60)
    if minutes < _stall_alert_minutes(project_root):
        return None
    return {"run_id": str(run_id), "minutes": minutes}


def _read_run_tail(run_file, max_lines: int = 1) -> list:
    """run/产物文件末行事件（复用 runs.py 公开 read_run_lines 的 64KB 尾窗读取）。

    延迟导入避免 core.dashboard 导入链（与 _terminal_status_map 同款）；
    只需末行时 max_lines=1 把尾窗解析成本压到最低。两个消费方：running
    判定取 ``runs/<run_id>.jsonl`` 末行；read_progress 的 current 取 mtime
    最晚产物（分片/主产物）末行——后者同款收敛对最新产物文件的二次整读
    （code-review item c5aa4e019015）。
    """
    from core.dashboard.data.runs import read_run_lines

    return read_run_lines(run_file, max_lines=max_lines)


def _terminal_status_map() -> dict:
    """run 终态事件类型集合（RUN_TERMINAL_STATUS_MAP 全量）。

    读 runs.py 公开常量 RUN_TERMINAL_STATUS_MAP（延迟解析避免 core.dashboard
    导入链）；终态全集以 core/dashboard/data/runs.py 的映射为单源，此处不
    手抄枚举（含 frozen-terminated/gate-blocked 在内的全集见该映射，与
    read_progress docstring 同口径，避免两处清单各自漂移）。
    """
    from core.dashboard.data.runs import RUN_TERMINAL_STATUS_MAP

    return dict(RUN_TERMINAL_STATUS_MAP)


def _run_stale_seconds() -> float:
    """run 产物 stale 阈值（读 runs.py 公开常量 RUN_STALE_SECONDS）。"""
    from core.dashboard.data.runs import RUN_STALE_SECONDS

    return float(RUN_STALE_SECONDS)


def local_today_str() -> str:
    """本地自然日字符串 YYYY-MM-DD（状态文件同日防重复基准，与自省同源）。"""
    return now_local().date().isoformat()  # SPEC-B 批④收拢


def _code_review_state_path(project_root) -> Path:
    return Path(project_root) / ".fenix" / "code_review_state.json"


def read_code_review_state(project_root) -> dict:
    """读取 ``.fenix/code_review_state.json``（同日防重状态）。"""
    return _read_json_file(_code_review_state_path(project_root))


def save_code_review_state(project_root, date_str: str) -> None:
    """写入 ``.fenix/code_review_state.json``（同日防重 + 窗口水位）。

    与自省状态文件解耦（MUST NOT 复用 self_review_state.json 的
    last_run_date——会被同轮自省检查点写为今天导致本车道永不派发）。

    add-code-review-run-at 3.1：新增 ``last_run_at``（本轮审查调度收尾时刻，
    aware ISO8601 本地时区表述，与 ``self_review_state.last_run_at`` 一致，
    读侧 ``_iso_to_aware_dt`` 直读）——审查窗口水位归审查车道自身，
    ``compute_window`` 优先读它（解耦触发时点后防「自省先跑覆写窗口」的
    覆盖缺口）；兼容保留 ``last_run_date`` 自然日防重字段。
    """
    path = _code_review_state_path(project_root)
    now = now_local()
    try:
        _atomic_write(
            path,
            json.dumps(
                {
                    "last_run_date": date_str,
                    "last_run_at": now.isoformat(),  # add-code-review-run-at 3.1 水位
                    "updated_at": now.isoformat(),  # SPEC-B 批④收拢
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    except OSError as e:
        _logger.warning("code_review: code_review_state.json 写入失败: %s", e)


# ── pending-writeoff 锚（evo-add-review-night-defer-snapshot-writeoff 3.1）──


def pending_writeoff_path(project_root) -> Path:
    """pending-writeoff 锚文件（error 收场抢救落账后、全仓核销解锁前的待办标记）。"""
    return code_review_dir(project_root) / "writeoff-pending.json"


def write_pending_writeoff(project_root, payload: dict) -> None:
    """覆盖写 pending-writeoff 锚（flock + 原子替换，与 items.jsonl 同风格）。

    写入点在 run_code_review 的 error 收场抢救段：inserted/updated > 0 时
    记 ``{run_id, inserted, updated, at}`` 待核销现场。覆盖写——新事故顶旧
    锚，只留最近一次待核销现场；清除点见 ``clear_pending_writeoff``。
    """
    path = pending_writeoff_path(project_root)

    def _do() -> None:
        _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2))

    _with_lock(path, _do)


def read_pending_writeoff(project_root) -> dict:
    """读 pending-writeoff 锚；缺失/损坏返回空 dict（＝无待核销现场）。"""
    return _read_json_file(pending_writeoff_path(project_root))


def clear_pending_writeoff(project_root) -> None:
    """清除 pending-writeoff 锚（核销执行且 resolved>0，或覆盖完整成功收尾）。"""
    path = pending_writeoff_path(project_root)

    def _do() -> None:
        path.unlink(missing_ok=True)

    _with_lock(path, _do)


# ── 修复 SPEC 生成（复用 evolution 链路，分组 6） ──────────────────

_KEBAB_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _spec_yaml_content(created: str) -> str:
    """生成 .spec.yaml 内容（f-string 组装；`.format()` 实参为关键字、
    arity-guard 无法解析会误报「实参必填位不足」，故用 f-string 展开）。"""
    return f"schema: spec-driven\ncreated: {created}\nmode: full\n"


def _slugify(text: str) -> str:
    """把任意文本推导为 kebab-case slug（^[a-z0-9][a-z0-9-]*$）。

    ``re.sub(r"[^a-z0-9]+", "-", ...).strip("-")`` 归一后 s 首字符必为
    [a-z0-9]（或 s 为空，已回退 "fix"），故无需再判「非字母数字前缀」的
    不可达分支（code-review item 4796c2e0774c 已移除该死代码）。
    """
    if not isinstance(text, str):
        text = str(text)
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not s:
        s = "fix"
    # 截断到安全长度：title 由 LLM 原样入库可达数百字符，不截断会使派生目录
    # 名（fix-cr-<slug>、drafts/specs/<capability>）超文件系统单段 255 字节
    # 上限，草稿落盘直接 OSError；重名由 -<fp[:6]> 后缀消解兜底
    #（code-review item 7467b582942b）
    return s[:50].rstrip("-")


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
    # severity 门限（evo-add-codefix-severity-batch-gate 2.2）：候选层与
    # code_fix.select_batch 应用同一谓词（severity_gate_open 单一函数），
    # Dashboard 手工触发与 scheduled 触发走同门——未到周批窗口的纯
    # minor/info 触发按空批处理并说明原因。组放行窗口对 open 池判定
    #（与选批层同口径：窗口到期累积的挂起条目整组放行；resolved/
    # ignored 条目的残留老锚不参与——2026-10-11 口径修复）。gate 关闭
    #（缺省）时谓词恒放行，此处零分支旁路。
    gate = severity_gate_config(project_root)
    release = severity_gate_release_due(
        [rec for rec in items.values()
         if isinstance(rec, dict) and rec.get("status") == "open"], gate
    )
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
        if not severity_gate_open(rec, gate, release_due=release):
            skipped.append({"item_id": item_id, "reason": "severity_deferred"})
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
        if any(s.get("reason") == "severity_deferred" for s in skipped):
            # 纯 minor/info（或含此类条目）未到周批窗口：按空批处理并说明
            # 原因（spec「手工通道绕过被拒」Scenario），非错误态文案分级
            error = (
                "选中条目均低于严重度门限（min_immediate_severity="
                f"{gate['min_immediate_severity']}），已挂起待周批窗口"
                f"（minor_batch_cadence={gate['minor_batch_cadence']} 天）"
                "统一修复"
            )
        else:
            error = "无有效的 open 条目可生成"
        return {
            "ok": False,
            "spec_name": None,
            "skipped": skipped,
            "error": error,
            "start_after": None,
        }

    # slug 推导（首个候选的 category 或短标题）
    first = candidates[0]
    # _slugify 输出恒匹配 _KEBAB_RE（见其 docstring），单次推导即终值，
    # 无需二次回退（item 23d18af486a2：回退分支不可达，已删）。
    slug = _slugify(str(first.get("category") or "") or str(first.get("title") or ""))
    first_fp = str(first.get("fingerprint") or "")
    name = _resolve_fix_spec_name(project_root, state_machine, slug, first_fp)
    if name is None:
        return {
            "ok": False,
            "spec_name": None,
            "skipped": skipped,
            "error": f"SPEC 名冲突无法消解（base fix-cr-{slug}）",
            "start_after": normalized_sa,
        }

    capability = slug or "fix"
    created = now_local().strftime("%Y-%m-%d")  # SPEC-B 批④收拢
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
        return {
            "ok": False,
            "spec_name": None,
            "skipped": skipped,
            "error": f"草稿落盘失败: {e}",
            "start_after": normalized_sa,
        }

    # 同源 lint 预检（violation → 删除草稿、条目状态不变、返回错误）
    violations = _lint_draft(draft_root, project_root)
    if violations:
        shutil.rmtree(draft_root, ignore_errors=True)
        return {
            "ok": False,
            "spec_name": None,
            "skipped": skipped,
            "error": f"lint 未通过: {'；'.join(violations)}",
            "start_after": normalized_sa,
        }

    # 落地：复制到 spec/changes → git add+commit → add_spec
    dest = Path(project_root) / "spec" / "changes" / name
    if dest.exists():
        # 判重（_spec_name_conflicted）正确时本分支不可达；触达即并发生成
        # 竞态。安全方向是失败而非删除覆盖——rmtree 会毁掉另一侧已提交并
        # 注册的 SPEC，STATE 里留下磁盘目录已消失的 drafted 条目。
        shutil.rmtree(draft_root, ignore_errors=True)
        return {
            "ok": False,
            "spec_name": None,
            "skipped": skipped,
            "error": f"目标目录已存在（spec/changes/{name}），疑似并发生成",
            "start_after": normalized_sa,
        }
    try:
        shutil.copytree(draft_root, dest)
    except OSError as e:
        shutil.rmtree(draft_root, ignore_errors=True)
        return {
            "ok": False,
            "spec_name": None,
            "skipped": skipped,
            "error": f"复制到 spec/changes 失败: {e}",
            "start_after": normalized_sa,
        }

    ok, err = _git_commit(project_root, name)
    if not ok:
        # add 已写入索引而 commit 失败（hook 拒绝 / index.lock 竞争 / 缺
        # identity 等）时，先撤回 pathspec 暂存项再删工作树副本，避免留下
        # 「暂存新文件 + 工作树已删」的脏索引状态。
        _git(project_root, ["reset", "-q", "--", f"spec/changes/{name}"])
        shutil.rmtree(dest, ignore_errors=True)
        shutil.rmtree(draft_root, ignore_errors=True)
        return {
            "ok": False,
            "spec_name": None,
            "skipped": skipped,
            "error": f"git commit 失败: {err}",
            "start_after": normalized_sa,
        }

    registered = False
    try:
        if state_machine is not None:
            entry = {"status": "drafted", "priority": 5}
            # start_after 非空 = 定时拾取 / 待激活（add_spec 透传任意键）。
            # 与 evolution.accept 同形：哨兵 "manual" 原样落入，不做时间换算。
            if normalized_sa:
                entry["start_after"] = normalized_sa
            registered = state_machine.add_spec(name, entry)
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
            "start_after": normalized_sa,
        }

    shutil.rmtree(draft_root, ignore_errors=True)

    # 成功后把参与条目置 in_spec 并写 spec_name（in_spec 由生成链路置入，
    # 不经 set_item_status——后者仅允许人工 open/ignored，design 1.5）。
    # 置位失败（_atomic_write 磁盘满/权限）时 SPEC 已提交并注册为 drafted，
    # 裸抛会让调用方误判整批未生成而重试，_spec_name_conflicted 会给同一批
    # 问题追加 -<fp[:6]> 生成第二个修复 SPEC——记 warning 并返回错误提示人工核对。
    try:
        _mark_in_spec(project_root, [rec["item_id"] for rec in candidates], name)
    except OSError as e:
        _logger.warning(
            "code_review: SPEC %s 已生成但台账条目置位 in_spec 失败: %s", name, e
        )
        return {
            "ok": False,
            "spec_name": name,
            "skipped": skipped,
            "error": f"SPEC {name} 已生成并提交，但台账条目置位 in_spec 失败: {e}（请勿重试生成以免重复 SPEC，需人工核对条目）",
            "start_after": normalized_sa,
        }
    return {
        "ok": True,
        "spec_name": name,
        "skipped": skipped,
        "error": None,
        "start_after": normalized_sa,
    }


def _mark_in_spec(project_root, item_ids: List[str], spec_name: str) -> None:
    """把条目置 in_spec 并写入 spec_name（生成链路内部写路径，读-改-写锁内原子）。

    状态守卫与 ``mark_resolved`` / ``mark_ignored`` 对齐：仅 ``status ==
    "open"`` 的条目可置——generate_fix_spec 选出候选到置位之间隔着 lint/
    git 提交等秒级耗时，窗口内已被终态化（resolved/ignored）的条目跳过
    不覆写，不冲掉核销/忽略记录。

    读降级（items.jsonl OSError 类不可读）时记 WARNING 并上抛 ``OSError``：
    SPEC 此刻已提交并注册为 drafted，静默跳过会让调用方误判置位成功、条目
    留在 open 而下轮重复立项（code-review item 8e0e362859de）；上抛复用
    generate_fix_spec 的置位写失败错误通道（SPEC 已生成、请勿重试生成、
    需人工核对条目）。
    """
    path = items_path(project_root)

    def _apply(current: Dict[str, dict]) -> bool:
        changed = False
        for iid in item_ids:
            rec = current.get(iid)
            # 同 mark_resolved / mark_ignored 守卫（c729af4d1750）：并发
            # 窗口内被人工或 code-fix 车道终态化的条目跳过，不翻回 in_spec
            if rec is None or rec.get("status") != "open":
                continue
            rec["status"] = "in_spec"
            rec["spec_name"] = spec_name
            # 周批晋级条目立项即清挂起标记（evo-add-codefix-severity-batch-
            # gate：spec「批完成后 deferred 标记清除」——in_spec 立项是批次
            # 生效时点，标记不再参与任何判定，残留只会污染台账展示）
            rec.pop(SEVERITY_DEFERRED_FIELD, None)
            rec.pop(SEVERITY_DEFERRED_SINCE_FIELD, None)
            changed = True
        return changed

    # 读降级 MUST 上抛而非静默 return（code-review item 8e0e362859de）：
    # SPEC 此刻已提交并注册，静默跳过会让 generate_fix_spec 以 ok=True
    # 收尾，条目留在 open、下轮对同一批问题重复立项；上抛 OSError 复用
    # 调用方置位写失败的既有错误通道（SPEC 已生成、勿重试、需人工核对）。
    _with_lock(
        path,
        lambda: _mutate_items_unlocked(
            path, _apply, degraded_note="in_spec 置位未落盘", strict_degraded=True
        ),
    )


def mark_resolved(project_root, item_ids: List[str]) -> int:
    """自动修复车道核销（add-code-review-auto-fix D7）：把指定条目置 ``resolved``。

    与 ``set_item_status`` 的分工：后者是**人工**流转（仅 open/ignored），
    ``resolved`` 不可人工置入；本函数是**框架内部写路径**，形态对齐
    ``_mark_in_spec``（读-改-写走 ``_with_lock`` + ``_atomic_write``，只动
    命中条目）。约束（design 契约要点）：``resolved`` 只能由**合回成功**
    驱动——调用方（code-fix 批 worker）MUST 在 merge-back 成功后才调本函数，
    回归未通过或未合回时 MUST NOT 置 resolved。状态守卫与 ``mark_ignored``
    对齐：仅 ``status == "open"`` 的条目可置——``in_spec``（已立项）、
    ``ignored``（人工误报终态）、``resolved``（已核销）一律跳过不覆写，
    批重放/并发窗口不冲掉人工意图、不虚增进度。

    参数:
        project_root: 项目根（主树——台账在主树）。
        item_ids: 本批中产物行 ``status == "fixed"`` 的条目 id 列表。
            缺失的 item_id 静默跳过（不报错——台账并发演进下属正常态）。

    返回:
        命中并置为 resolved 的条目数（仅 open→resolved 真实迁移才计数；供
        进度 ``done`` 累计，MUST 以本值为准而非批条数——skipped 与未命中不计入）。
    """
    path = items_path(project_root)
    hit = 0
    now = _now_iso()

    def _apply(current: Dict[str, dict]) -> bool:
        nonlocal hit
        for iid in dict.fromkeys(item_ids):  # 去重：重复 id 只命中一次
            rec = current.get(iid)
            if rec is None or rec.get("status") != "open":  # 同 mark_ignored 守卫
                continue
            rec["status"] = "resolved"
            rec["resolution"] = "code-fix-auto"
            rec["resolved_at"] = now  # 同 mark_ignored 的 ignored_at / resolve_snapshot 的 resolved_at
            # 核销即批次完成（evo-add-codefix-severity-batch-gate）：清挂起
            # 标记，与 _mark_in_spec 同口径
            rec.pop(SEVERITY_DEFERRED_FIELD, None)
            rec.pop(SEVERITY_DEFERRED_SINCE_FIELD, None)
            hit += 1
        return bool(hit)

    # 读降级拒写（code-review item 9a358bba128c）：保持台账原样
    _with_lock(path, lambda: _mutate_items_unlocked(path, _apply, degraded_note="resolved 核销跳过落盘"))
    return hit


def mark_ignored(
    project_root, item_ids: List[str], reasons: Optional[Dict[str, str]] = None,
    by: str = "code-fix-agent",
) -> int:
    """code-fix 车道 ignored 置入（LLM 拒绝出口，2026-09-23）。

    与 ``set_item_status``（**人工**流转，仅 open/ignored）的分工：本函数是
    **框架内部写路径**（形态对齐 ``mark_resolved``：读-改-写走 ``_with_lock``
    + ``_atomic_write``，只动命中条目），由 code-fix 批 worker 在解析产物行
    时调用——agent 对条目显式标注 ``skip_reason ∈ {false_positive,
    not_worth_fixing}``（判误报/不值得修）时，把该条目置终态 ``ignored``，
    不再跨链重修。约束：仅 ``status == "open"`` 的条目可置（``in_spec`` 已
    立项的 MUST NOT 被车道降级；``resolved`` 是合回专属，同 ``mark_resolved``
    的分工契约）；记录 ``ignored_by`` / ``ignored_reason`` / ``ignored_at``
    供人工回溯与后续误判重开。

    参数:
        project_root: 项目根（主树——台账在主树）。
        item_ids: 产物行 ``status == "skipped"`` 且 skip_reason 属可忽略
            集合的条目 id 列表。缺失的 item_id 静默跳过（并发演进下属正常态）。
        reasons: ``item_id → skip_reason`` 映射（记入 ``ignored_reason``，
            缺失记空串——标注缺失不影响置入，可忽略性由调用方按产物行过滤）。
        by: 记入 ``ignored_by`` 的来源标注。

    返回:
        命中并置为 ignored 的条目数。
    """
    path = items_path(project_root)
    hit = 0
    now = _now_iso()
    reason_map = reasons or {}

    def _apply(current: Dict[str, dict]) -> bool:
        nonlocal hit
        for iid in dict.fromkeys(item_ids):  # 去重：重复 id 只命中一次
            rec = current.get(iid)
            if rec is None or rec.get("status") != "open":
                continue
            rec["status"] = "ignored"
            rec["ignored_by"] = by
            rec["ignored_reason"] = reason_map.get(iid, "")
            rec["ignored_at"] = now
            hit += 1
        return bool(hit)

    # 读降级拒写（code-review item 9a358bba128c）：保持台账原样
    _with_lock(path, lambda: _mutate_items_unlocked(path, _apply, degraded_note="ignored 置位跳过落盘"))
    return hit


def _indent_block(text: str, prefix: str = "  ") -> List[str]:
    """把多行文本逐行加前缀（空行保留为裸空行），供嵌入 Markdown 列表。

    描述/证据字段可能含换行（实测台账存在多行 description）。直接内插会破坏
    列表缩进或撞上 tasks.md 的行首正则，故一律逐行加前缀后再拼接。
    """
    if not text:
        return []
    return [f"{prefix}{ln}" if ln.strip() else "" for ln in str(text).splitlines()]


def _one_line(text: str) -> str:
    """把标题类字段折叠为单行（连续空白含换行折叠为单空格、去首尾）。

    title 来自 LLM 产出原样入库（upsert_findings 仅 str() 不折叠），含换行
    时直接内插会把 `###`/`####` 标题行或 `- [ ] N.N` 任务行第二行起顶成裸
    文本——不再匹配行首形态，任务在进度跟踪与归属校验里静默消失。与
    _indent_block 同向防御（code-review item 1347190ca3c6）。
    """
    return re.sub(r"\s+", " ", str(text)).strip()


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
        lines.append(f"### [{it.get('severity')}] {_one_line(it.get('title'))}")
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
        lines.append(f"#### `{it.get('file')}:{it.get('line')}` — {_one_line(it.get('title'))}")
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
    """生成 design.md：Context/Decisions 为静态文案，「逐条修复方向」段
    引用 items（与 _proposal_md/_spec_md/_tasks_md 同口径）。

    注：code-review item 457092d12994 称本函数 items 未使用——经复核为误报，
    下方循环实际使用 items 渲染逐条修复方向，故保持签名不变。
    """
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
        lines.append(f"### `{it.get('file')}:{it.get('line')}` — {_one_line(it.get('title'))}")
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
            f"- [ ] {idx}.{idx} {_one_line(it.get('title'))} — {it.get('file')}:{it.get('line')}"
        )
        lines.append("")
        lines.extend(_problem_lines(it))
    lines.append("")
    return "\n".join(lines)


def _lint_draft(draft_dir_: Path, project_root) -> List[str]:
    """对草稿目录执行与 daemon 晋升同源的 lint 预检（薄委托 evolution.lint_draft）。

    唯一实现在 ``core.evolution.lint_draft``（sys.path 注入 + 两级失败语义：
    lint 函数自身异常 fail-open、``core.deliverables`` 导入失败显式上抛），
    本函数仅转发，防两套实现漂移（code-review item 2beb5528e1b9）。函数内
    延迟导入同 fenixd.py 既有口径；fail-open WARNING 的日志前缀随唯一实现
    落 ``fenixd.evolution`` 通道。
    """
    from core.evolution import lint_draft

    return lint_draft(draft_dir_, project_root)


def _git_commit(project_root, spec_name: str) -> Tuple[bool, str]:
    """仅提交目标 spec 目录（薄委托 evolution._git_commit 唯一实现）。

    add 与 commit 均以 ``spec/changes/<name>`` 同一 pathspec 限定（MUST NOT
    ``git add -A`` / ``git add .``），返回 ``(ok, error)``、error 前缀区分
    add / commit 阶段——语义详见唯一实现 docstring（code-review item
    2beb5528e1b9，单点演进防再漂移）。函数内延迟导入同 fenixd.py 既有口径。
    """
    from core.evolution import _git_commit as _evolution_git_commit

    return _evolution_git_commit(project_root, spec_name)
