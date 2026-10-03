"""
admin_store.py — Administrator 告警/处置记录持久化（.fenix/admin_alerts.json）。

统一存三类记录（append-only JSON 数组，同文件）：
  - kind="signal"      监视器检测到的困境信号（审计 + 节流依据）
  - kind="escalation"  需人工介入的升级告警（未处理时 Dashboard 横幅展示）
  - kind="disposition" Administrator 完成的一次处置记录
  - kind="info"        纯留痕信息（evo-reduce-stale-code-selfheal-noise）：
                       自愈健康路径的 stale_code 留痕，无处理生命周期、
                       不进人工队列，仅 latest_signal 窗口去重可见

并发安全：daemon 监视线程与 Dashboard server 是独立进程，所有读改写
都在 fcntl.flock 排他锁内进行（锁文件与数据文件同路径 + .lock）。
"""

import fcntl
import json
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .alert_lifecycle import AUTO_RESOLVE_BY
from core.timelib import parse_ts


# 记录种类
SIGNAL = "signal"
ESCALATION = "escalation"
DISPOSITION = "disposition"
# evo-reduce-stale-code-selfheal-noise 2.1：info 级留痕 kind。无处理生命周期
# （mark_handled/unhandled/pending_escalations 仍仅锚定 ESCALATION，口径不变），
# 仅参与 latest_signal 窗口去重（见白名单）。
INFO = "info"

# 记录数上限（2026-09-01 用户决策）：任何写回时自动裁剪，只保留最近 150 条。
# 消费方（latest_signal 冷却去重、auto_resolve 按 id 闭环）均只依赖近期记录，
# 裁掉最旧历史不影响语义。
MAX_RECORDS = 150

# dispute 裁决审计（DisputeAuditStore）记录数上限：单条含 verdicts 全文与
# diff，体积远大于告警记录，故上限取同类量级但放宽到 500 条；超限裁掉最旧
# 历史（judge 裁决为低频事件，豁免匹配只关心在册凭据的存在性，裁剪后仍
# 保留足够近期的可回滚凭据）。
MAX_AUDIT_RECORDS = 500

# 归档（add-alerts-archive-and-overview-cache 1.1）：活跃文件裁剪时被移出的
# 最旧记录逐行追加写入归档旁路文件（JSONL，每行一条完整 JSON 记录），不再
# 直接丢弃——处置记录是唯一的运维审计载体，滚动出局后仍需可追溯。归档自身
# 设滚动上限（独立于活跃上限），耗尽后最旧历史按序永久淘汰。
ARCHIVE_NAME = "admin_alerts_archive.jsonl"
MAX_ARCHIVE_RECORDS = 2000

# 降噪分级（2026-09-01 用户决策）：只有 critical/major 默认进人工待处理
# 队列；warning/minor 写入即自动标记已处理（仍留历史记录，不弹横幅）。
HUMAN_SEVERITIES = ("critical", "major")


def severity_needs_human(severity: str) -> bool:
    return (severity or "").lower() in HUMAN_SEVERITIES


def evidence_project(evidence: str) -> str:
    """从 evidence 串（``项目名=<name>; ...``）按字段解析项目名，全等比较用。

    「项目名=」字段解析的唯一实现（原 mergeback.py / code_fix.py /
    settings_routes 各持的 `_evidence_project` 副本已收敛至此）。evidence 的
    生产点格式不一（dashboard 侧可能只有裸 ``项目名=<name>`` 无尾随分隔符），
    不能靠带分隔符的子串匹配；项目名互为前缀时（``web`` 与 ``webapp``）
    也不得互撞（code-review item 29958284895a）。
    """
    for seg in (evidence or "").split(";"):
        seg = seg.strip()
        if seg.startswith("项目名="):
            return seg[len("项目名="):].strip()
    return ""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fsync_parent_dir(path: Path) -> None:
    """rename 原子替换后刷父目录项，保证替换结果掉电不回退（尽力而为）。

    临时文件 fsync 只保证文件内容落盘，rename 的目录项变更是否持久化取决于
    父目录是否刷盘——不刷则掉电重启后文件可能整体回退为旧内容（code-review
    item 74e17a6b9d5c）。目录 fsync 在个别文件系统上不支持或失败（EINVAL 等），
    静默忽略，此时仍保留进程级崩溃安全保证。
    """
    try:
        dfd = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dfd)
    except OSError:
        pass
    finally:
        os.close(dfd)


class AdminStore:
    """读写 .fenix/admin_alerts.json 的存储层。

    线程/进程安全：追加与标记已处理均在 flock 排他锁内完成读-改-写；
    写入用临时文件 + rename 保证原子性，崩溃不损坏既有记录。
    """

    def __init__(self, project_root, logger=None):
        self.project_root = Path(project_root)
        self.alerts_path = self.project_root / ".fenix" / "admin_alerts.json"
        self.archive_path = self.project_root / ".fenix" / ARCHIVE_NAME
        self._lockfile = Path(str(self.alerts_path) + ".lock")
        self._thread_lock = threading.Lock()  # 进程内互斥（跨线程）
        self._logger = logger

    # ── 内部：加锁读/写 ───────────────────────────────────────────

    def _lock(self):
        self._lockfile.parent.mkdir(parents=True, exist_ok=True)
        return open(self._lockfile, "w")

    def _read_unlocked(self, path: Path) -> "tuple[list, bool]":
        """读取告警记录；返回 ``(records, corrupt)``。

        ``corrupt=True`` 表示「本次读取因解析失败走了损坏处理路径」——损坏
        文件已改名 ``.corrupt-<ts>`` 留底取证、返回空集合（fix-robustness-edge-
        cases 2.1）。留底改名后的 ``[]`` 与「文件本不存在 / 合法空数组」在
        返回值上不可区分，故下限保护（``_mutate``）必须凭本信号的显式语义
        判定，不得按实现默认推断（design D2：否则二选一皆错——恒不触发则
        静默清库仍在，恒触发则拦掉损坏后的合法恢复写入）。正常空文件/合法
        空数组路径恒 ``corrupt=False``，不得被下限保护误拦。
        """
        if not path.exists():
            return [], False
        try:
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                # 正常空文件（0 字节/纯空白）与「合法空数组」同语义：非损坏，
                # 恒 corrupt=False（不留底、本次写回放行）。json.loads("") 会抛
                # JSONDecodeError，不在此短路会被误判为损坏留底、拒掉当次写回
                # （code-review item 2d386f296ace）。
                return [], False
            data = json.loads(text)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            # 非法 UTF-8 字节（磁盘损坏/外部工具误写）抛 UnicodeDecodeError
            # （ValueError 子类，上两类均不覆盖）——同走留底取证路径
            return [], self._quarantine_corrupt(path)
        if not isinstance(data, list):
            # 非数组内容同样无法解读（读-改-写会以空为底抹掉全部历史）——
            # 与非法 JSON 同视为损坏，一并留底
            return [], self._quarantine_corrupt(path)
        recs = [e for e in data if isinstance(e, dict)]
        # 存量（修复前落盘）dict/list evidence 读侧归一为字符串，一次读即自愈
        # （回归 fix-alert-evidence-render-crash）：写入口修复只能挡住新写入，
        # 已在 admin_alerts.json 里的结构化 evidence 仍会让 Dashboard API
        # 下发对象、前端白屏，读侧统一归一保证消费端恒拿 str 或 None。
        for e in recs:
            ev = e.get("evidence")
            if ev is not None and not isinstance(ev, str):
                e["evidence"] = json.dumps(ev, ensure_ascii=False)
        return recs, False

    def _quarantine_corrupt(self, path: Path) -> bool:
        """把损坏的告警文件改名 ``<name>.corrupt-<ts>`` 留底，返回是否成功。

        读损坏的取证保留：改名后返回空集合，且不覆盖损坏证据（后续写回受
        ``_mutate`` 下限保护拒绝）。改名失败（OSError，权限/硬件异常）仍返回
        True——损坏语义不变，写回同样被拒（fail-closed：宁可告警暂时写不进，
        不可静默清掉全部历史），需人工介入修复。
        """
        # 纳秒级时间戳：秒级后缀下同秒二次留底会被 rename 静默覆盖、丢失取证
        dest = path.with_name(f"{path.name}.corrupt-{time.time_ns()}")
        try:
            if path.exists():
                path.rename(dest)
            if self._logger is not None:
                self._logger.warning(
                    "admin_store",
                    f"告警文件读取失败，已留底改名 {dest}（本次返回空集合；"
                    "写回受下限保护，不覆盖损坏证据）",
                )
        except OSError:
            if self._logger is not None:
                self._logger.warning(
                    "admin_store",
                    f"告警文件损坏留底改名失败 {path}（写回仍将被拒，需人工介入）",
                )
        return True

    def _read_locked(self) -> list:
        # 读路径加锁口径与 read_archive / DisputeAuditStore.read_all 统一：
        # _thread_lock（同进程跨线程串行）+ flock（跨进程互斥，每次经
        # _lock() 新开 fd，同进程跨 fd 亦互斥）双锁，不留单 flock 特例
        with self._thread_lock:
            with self._lock() as lf:
                fcntl.flock(lf, fcntl.LOCK_EX)
                try:
                    records, _corrupt = self._read_unlocked(self.alerts_path)
                    return records
                finally:
                    fcntl.flock(lf, fcntl.LOCK_UN)

    def _write_unlocked(self, records: list):
        """原子写（临时文件 + rename），调用方须已持有文件排他锁。"""
        self.alerts_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path_str = tempfile.mkstemp(
            prefix=".admin_alerts.",
            suffix=".tmp",
            dir=str(self.alerts_path.parent),
        )
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.rename(str(tmp_path), str(self.alerts_path))
            _fsync_parent_dir(self.alerts_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _mutate(self, fn, skip_unchanged: bool = False, refuse_returns_none: bool = False):
        """在单次排他锁内完成读-改-写，返回 fn(records) 的结果。

        跨进程并发（监视线程 append 与 Dashboard mark_handled）若分别在两次
        锁获取中读改写会互相覆盖丢失记录，因此必须一次性持锁完成。
        skip_unchanged=True 时（add-alert-auto-resolve D1）：fn 返回假值
        （无任何变更）则跳过写回，文件 mtime 保持不变。

        写回前自动裁剪到最近 MAX_RECORDS 条（新记录在数组末尾，删头部最旧的）。

        写回下限保护（fix-robustness-edge-cases 2.2）：当本次读取因损坏走了
        留底路径（``_read_unlocked`` 的 corrupt 信号为真）时拒绝写回——否则
        读-改-写会以空数组为底，把损坏文件里的全部既有历史静默抹掉。该保护
        仅凭 corrupt 信号触发：文件不存在/合法空数组路径恒放行，留底改名后
        的下一次 mutate 读到的是缺失文件（干净空集合、corrupt=False），
        恢复写入不被拦（scenario「损坏后恢复写入」）。

        refuse_returns_none=True（code-review item 2570ca391771）：拒写时返回
        None 而非 fn 结果——fn 已在内存生效但记录未落盘，调用方（append /
        append_if_absent / merge_signal）据此把返回按未落地处理，不再把拒写
        伪装成成功（merge_signal 把 None 转译为 (None, False) 元组）。
        默认 False：其余调用方（mark_* 的布尔/计数返回值）行为保持不变。
        """
        with self._thread_lock:
            with self._lock() as lf:
                fcntl.flock(lf, fcntl.LOCK_EX)
                try:
                    records, corrupt = self._read_unlocked(self.alerts_path)
                    result = fn(records)
                    if skip_unchanged and not result:
                        return result
                    if corrupt:
                        # [fenix-ignore:4c8e1dfdd3f6] mark 族 mutate 全部带 skip_unchanged=True 且 corrupt 读取恒返回空记录，fn 对空记录必返假值并提前 return，本分支对 mark 族不可达，其 False/0 返回值已是如实的「未落盘」信号，不存在假成功
                        # 旧记录整体不可读（已留底取证）：拒绝本次写回
                        if self._logger is not None:
                            self._logger.error(
                                "admin_store",
                                "告警文件损坏留底后拒绝写回（历史不覆盖，"
                                "待人工介入；留底后新告警恢复写入不被拦）",
                            )
                        return None if refuse_returns_none else result
                    if len(records) > MAX_RECORDS:
                        trimmed = records[:-MAX_RECORDS]
                        del records[:-MAX_RECORDS]
                        # 叙事侧车级联删除（upgrade-narrative-to-investigation
                        # 3.4）：被裁告警的补叙侧车同步清理防孤儿堆积；删除
                        # 失败仅 WARNING 不阻断清理主流程（残留侧车渲染按
                        # alert_id 匹配不到即忽略，无害）
                        self._cleanup_narrative_sidecars(trimmed)
                        # 归档与裁剪同锁完成（spec：裁剪与归档之间不得丢记录）；
                        # 归档失败仅记日志，活跃文件写回主路径照常执行（D2 软失败）
                        self._archive_unlocked(trimmed)
                    self._write_unlocked(records)
                    return result
                finally:
                    fcntl.flock(lf, fcntl.LOCK_UN)

    # ── 叙事侧车级联清理（upgrade-narrative-to-investigation 3.4）──────

    def _cleanup_narrative_sidecars(self, trimmed: list) -> None:
        """被裁告警的叙事侧车级联删除（.fenix/admin_alerts_narrative/<id>.json）。

        D2 软失败：删除失败仅 WARNING 留痕、绝不抛出——清理主流程（活跃文件
        写回 + 归档）永不被侧车清扫拖挂；残留侧车渲染按 alert_id 匹配不到
        即忽略，仅占磁盘无害。
        """
        try:
            from core.adjudication_narrative import delete_narrative_sidecars

            ids = [r.get("id") for r in trimmed if isinstance(r, dict) and r.get("id")]
            if ids:
                delete_narrative_sidecars(self.project_root, ids)
        except Exception as e:
            if self._logger is not None:
                try:
                    self._logger.warning(
                        "admin_store",
                        f"叙事侧车级联删除失败（不阻断清理主流程）: {e}",
                    )
                except Exception:
                    pass

    # ── 归档（add-alerts-archive-and-overview-cache 1.1/1.2）──────

    def _archive_unlocked(self, trimmed: list):
        """被裁记录归档（调用方须已持有文件排他锁，与裁剪同锁防丢记录）。

        D1：JSONL 逐行追加（O(1)，无需读改写整文件——150 条池高频裁剪下
        数组格式每次归档都要全文件重写会放大 IO）；写入顺序即裁剪顺序即
        时间正序。D2 软失败：归档是审计增强不是主数据，写失败（磁盘满/
        权限/路径被目录占位）只记日志不抛出，活跃文件写回主路径永不被
        归档拖挂。追加成功后在同锁内执行归档自身滚动裁剪（上限独立于
        活跃上限，防归档无界增长）。
        """
        if not trimmed:
            return
        try:
            self.archive_path.parent.mkdir(parents=True, exist_ok=True)
            with self.archive_path.open("a", encoding="utf-8") as f:
                for rec in trimmed:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as exc:
            if self._logger is not None:
                self._logger.warning(
                    "admin_store",
                    f"归档写入失败（不阻塞活跃写回）: {type(exc).__name__}: {exc}",
                )
            return
        self._trim_archive_unlocked()

    def _trim_archive_unlocked(self) -> None:
        """归档自身滚动裁剪（调用方须已持有排他锁）：记录数超
        MAX_ARCHIVE_RECORDS 时保留末尾 N 行（整文件重写，临时文件 + rename
        原子替换，与 DisputeAuditStore._trim_unlocked 同模式）。裁剪幂等：
        未超限零写动作。读取/写失败按无归档处理（不抛出）。"""
        try:
            lines = self.archive_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return
        lines = [ln for ln in lines if ln.strip()]
        if len(lines) <= MAX_ARCHIVE_RECORDS:
            return
        fd, tmp_str = tempfile.mkstemp(
            prefix=".admin_alerts_archive.",
            suffix=".tmp",
            dir=str(self.archive_path.parent),
        )
        tmp_path = Path(tmp_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for ln in lines[-MAX_ARCHIVE_RECORDS:]:
                    f.write(ln + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.rename(str(tmp_path), str(self.archive_path))
            _fsync_parent_dir(self.archive_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def read_archive(self) -> list:
        """读取归档文件全部记录（存储原序：时间正序，最新在末尾）。

        供归档只读出口（dashboard 数据层 get_archived_activities）使用，
        不与活跃文件合并、不进任何缺省读路径。与写回一致在排他锁内读取
        （滚动裁剪经 rename 整文件替换，无锁并发读最坏读到整文件，容错
        跳过非 JSON 行兜底）；损坏行跳过、缺失/不可读返回空列表。
        """
        if not self.archive_path.exists():
            return []
        out: list = []
        try:
            with self._thread_lock:
                with self._lock() as lf:
                    fcntl.flock(lf, fcntl.LOCK_EX)
                    try:
                        with self.archive_path.open(encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    d = json.loads(line)
                                except json.JSONDecodeError:
                                    continue
                                if isinstance(d, dict):
                                    out.append(d)
                    finally:
                        fcntl.flock(lf, fcntl.LOCK_UN)
        except (OSError, UnicodeDecodeError):
            return []
        return out

    # ── 公开 API ─────────────────────────────────────────────────

    @staticmethod
    def _normalize_entry(entry: dict) -> dict:
        """补齐 id/created/handled 等默认字段（append / merge_signal 共用）。"""
        rec = dict(entry)
        rec.setdefault("id", uuid.uuid4().hex[:12])
        rec.setdefault("created", _utcnow_iso())
        rec.setdefault("handled", False)
        rec.setdefault("handled_at", None)
        rec.setdefault("severity", "major")
        rec.setdefault("signal_type", None)
        rec.setdefault("spec", None)
        rec.setdefault("description", "")
        rec.setdefault("evidence", None)
        rec.setdefault("action_taken", None)
        rec.setdefault("result", None)
        rec.setdefault("recommended_action", None)
        # evidence 契约恒为字符串（回归 fix-alert-evidence-render-crash）：
        # 写入口把 dict/list 结构化 evidence 序列化为 JSON 串，读侧（Dashboard
        # API / prompt 注入 / 冷却去重）拿到的 evidence 恒为 str 或 None，避免
        # 前端直接渲染对象白屏。字符串原样保留，缺省 None 不序列化为 "null"。
        evidence = rec.get("evidence")
        if evidence is not None and not isinstance(evidence, str):
            rec["evidence"] = json.dumps(evidence, ensure_ascii=False)
        # add-human-adjudication-choices 1.3：告警可选 choices 字段（裁决选项集
        # 快照，写告警时自注册表取）。append/merge_signal 原样透传；非法形态
        # （非列表 / 元素非 dict）归一为 None——读取路径按无选项处理，不抛异常。
        # 去重（merge_signal）只比对 (spec, signal_type, status_hash)，choices
        # 不参与状态变化判定，不会因新字段误判合并；无该字段的存量记录按无
        # 选项兼容读取。
        if "choices" in rec:
            ch = rec.get("choices")
            if not (isinstance(ch, list) and all(isinstance(c, dict) for c in ch)):
                rec["choices"] = None
        return rec

    def append(self, entry: dict) -> "dict | None":
        """追加一条记录，补齐 id/created/handled 等默认字段，返回落地后的记录。

        记录顺序：新记录追加到数组末尾（最近在后）。读侧按倒序返回。
        文件损坏留底被下限保护拒写时返回 None——记录未落盘，其 id 不构成
        mark_handled/mark_escalated 的有效锚点，调用方可按未落地处理
        （code-review item 2570ca391771）。
        """
        rec = self._normalize_entry(entry)

        def fn(records: list) -> bool:
            records.append(rec)
            return True

        written = self._mutate(fn, refuse_returns_none=True)
        return rec if written else None

    def append_if_absent(self, entry: dict, is_inflight) -> "dict | None":
        """单次排他锁内完成「在途查重 → 追加」（code-review item 0d7c2ef12e33）。

        旧模式 read_all() 查重后 append() 是 check-then-act：两次独立锁获取
        不原子，ThreadingHTTPServer 并发同参 POST 可都观测到空在飞集并各自
        append，产生重复信号（每个重复消耗一次 Administrator run）。
        ``is_inflight(record)`` 以已读取的记录逐条判定是否在途；无在途才写入。
        返回落地的记录；存在在途（未写）或文件损坏留底被下限保护拒写
        （记录未落盘，item 2570ca391771）时返回 None。
        """
        rec = self._normalize_entry(entry)

        def fn(records: list) -> bool:
            if any(is_inflight(r) for r in records):
                return False
            records.append(rec)
            return True

        written = self._mutate(fn, skip_unchanged=True, refuse_returns_none=True)
        return rec if written else None

    def merge_signal(self, entry: dict, status_hash: str):
        """沉淀式写入 per-spec 检测信号（admin-signal-consolidation D1）。

        同一 (spec, signal_type, status_hash) 视为「状态未变」：不新增记录、
        仅刷新 last_seen（合并），返回既有记录与 (record, is_new=False)；
        状态变化 / 首见时创建新记录并携带 status_hash / last_seen，
        返回 (record, is_new=True)。

        文件损坏留底被下限保护拒写时返回 (None, False)——记录未落盘
        （code-review item 27c156cb5272），不把内存记录伪装成新沉淀成功，
        调用方须按未落地处理（record is None 即判别依据）。

        ONLY 作用于 kind=signal 的 per-spec 检测记录：
          - 「写入即待唤起」型记录（STORED_SIGNAL_TYPES 由 pm_engine 直接
            append 写入、按 id 摄取 mark_escalated）不参与合并——其 id 是
            mark_escalated 的锚点，被合并/替换会触发该记录被反复摄取；
            且此类记录无 status_hash 字段，天然不会命中合并。
          - kind=escalation / disposition 记录永不参与合并（id 是
            mark_handled / auto_resolve 的闭环锚点，跨事件合并破坏语义）。

        合并仅改写 last_seen：不动 id / created（即 first_seen）/ handled；
        escalated 只允许单调升级（False→True，与 mark_escalated 同方向）——
        节流分支沉淀不会把已唤起过的记录回退为「未唤起」，唤起分支的合并
        会把仅节流沉淀过的记录升级为「已唤起」，绝不在 True→False 方向改写。

        不修改 append 的全局语义：既有消费方（pm_engine / dashboard UI /
        verify_report 等直接 append 写入）行为完全不变。
        """
        rec = self._normalize_entry(entry)
        rec["status_hash"] = status_hash
        rec.setdefault("last_seen", rec["created"])

        def mutate(records):
            spec = rec.get("spec")
            signal_type = rec.get("signal_type")
            # 倒序找（最新在后，合并目标为最近一条同 hash 记录）
            for existing in reversed(records):
                if existing.get("kind") != SIGNAL:
                    continue
                if existing.get("spec") != spec:
                    continue
                if existing.get("signal_type") != signal_type:
                    continue
                if existing.get("status_hash") != status_hash:
                    continue
                # 状态未变：仅刷 last_seen（first_seen=created 语义保留）
                existing["last_seen"] = _utcnow_iso()
                if rec.get("escalated") and not existing.get("escalated"):
                    existing["escalated"] = True  # 单调升级，绝不回退
                return existing, False
            records.append(rec)
            return rec, True

        written = self._mutate(mutate, refuse_returns_none=True)
        if written is None:
            # 拒写（文件损坏留底）：记录未落盘，返回可判别的 (None, False)
            # 而非把内存元组原样穿透伪装成新沉淀成功（item 27c156cb5272）
            return None, False
        return written

    def read_records(self) -> list:
        """读取全部记录（按存储原序：新记录在数组末尾，不排序）。

        供消费方全量扫描（按 key 幂等去重等与顺序无关的判定）使用，
        避免外部直调内部 ``_read_locked``；损坏/缺失返回空列表。每次
        调用重新解析文件，返回独立列表，与内部状态无共享引用。需要
        「最新的在前」排序视图请用 :meth:`read_all`。
        """
        return self._read_locked()

    def read_all(self) -> list:
        """读取全部记录（最新的在前）。损坏/缺失返回空列表。"""
        records = self._read_locked()
        # str(...) or ""：对 "created" 非字符串脏形态（null/数字等，人工修补/
        # 外部写入）设防，避免 str 与 int 等混排抛 TypeError 打挂全部读路径，
        # 与 latest_resolved_disposition 同口径
        records.sort(key=lambda e: str(e.get("created") or ""), reverse=True)
        return records

    def unhandled(self) -> list:
        """未处理的升级告警（kind=escalation 且未 handled），最新的在前。"""
        return [e for e in self.read_all() if e.get("kind") == ESCALATION and not e.get("handled")]

    def mark_handled(self, alert_id: str) -> bool:
        """将某条升级告警标记为已处理。返回是否找到并更新。"""

        def mutate(records):
            changed = False
            for rec in records:
                if rec.get("id") == alert_id and rec.get("kind") == ESCALATION:
                    if not rec.get("handled"):
                        rec["handled"] = True
                        rec["handled_at"] = _utcnow_iso()
                        changed = True
            return changed

        return self._mutate(mutate, skip_unchanged=True)

    def mark_signal_handled(self, alert_id: str, action_taken=None, result=None,
                            handled: bool = True) -> bool:
        """将某条 kind=SIGNAL 记录标记已处理（add-human-adjudication-choices 4.1）。

        ``mark_handled`` 仅匹配 ESCALATION（既有人工告警闭环锚点，语义不可
        放宽），而配置裁决类信号（build_artifact_paths_missing）写 kind=SIGNAL
        记录——alert-resolve 端点对其经本方法直接更新 handled 族字段。仅改写
        handled/handled_at（与 mark_handled 同集，不伪造 handled_by），已处理
        条目幂等返回 False。

        fix-global-signal-choice-execution 2.3：留痕与闭环解耦——
        - ``action_taken`` / ``result`` 非 None 时一并写入告警记录（choice
          执行的动作名与成败终态留痕；此前恒为 null）；
        - ``handled=False`` 只留痕不置 handled/handled_at（choice 执行失败
          路径专用：信号保留待重审，MUST NOT 闭环）；
        - 缺省调用（仅 alert_id）行为与历史完全一致：置 handled=true，已处理
          条目幂等返回 False（既有调用点不传参零行为变化）。
        """

        def mutate(records):
            changed = False
            for rec in records:
                if rec.get("id") == alert_id and rec.get("kind") == SIGNAL:
                    if handled and not rec.get("handled"):
                        rec["handled"] = True
                        rec["handled_at"] = _utcnow_iso()
                        changed = True
                    if action_taken is not None:
                        rec["action_taken"] = action_taken
                        changed = True
                    if result is not None:
                        rec["result"] = result
                        changed = True
            return changed

        return self._mutate(mutate, skip_unchanged=True)

    def mark_escalated(self, alert_id: str) -> bool:
        """将某条信号标记为已唤起 Administrator（escalated=True）。

        供「写入即待唤起」型信号（family_explosion：pm_engine 直接落库、由
        AdminMonitor 摄取唤起）去重使用：同记录只唤起一次。
        返回是否找到并更新。
        """

        def mutate(records):
            changed = False
            for rec in records:
                # 仅锚定 kind=SIGNAL，与 mark_handled（ESCALATION）/
                # mark_signal_handled（SIGNAL）同族判据对齐，避免把 escalation
                # 等非 signal 记录误标 escalated 并触发无谓写回
                if rec.get("id") == alert_id and rec.get("kind") == SIGNAL:
                    if not rec.get("escalated"):
                        rec["escalated"] = True
                        changed = True
            return changed

        return self._mutate(mutate, skip_unchanged=True)

    def mark_all_handled(self) -> int:
        """将所有未处理升级告警标记为已处理。返回处理数量。"""

        def mutate(records):
            changed = 0
            for rec in records:
                if rec.get("kind") == ESCALATION and not rec.get("handled"):
                    rec["handled"] = True
                    rec["handled_at"] = _utcnow_iso()
                    changed += 1
            return changed

        return self._mutate(mutate, skip_unchanged=True)

    def auto_resolve(self, resolutions: list) -> int:
        """批量自动闭环升级告警（add-alert-auto-resolve D3/D6）。

        resolutions 为 alert_lifecycle.find_resolvable 的输出：
        [{'id', 'spec', 'resolve_note'}]。仅改写 handled 族字段：
          handled=True、handled_by="auto-resolve"、handled_at=解除时刻、
          resolve_note=解除依据。不触碰其余字段，不伪造人工处理记录。

        MUST 跳过 handled=True 条目（人工记录不可覆盖）；单次排他锁内完成
        读-改-写（复用既有原子写与 .lock）；无可闭环条目时零写回（mtime 不变）。
        返回实际闭环数量。
        """
        notes = {r.get("id"): r.get("resolve_note") or "" for r in resolutions or [] if r.get("id")}
        if not notes:
            return 0

        def mutate(records):
            changed = 0
            resolved_at = _utcnow_iso()
            for rec in records:
                if rec.get("id") not in notes:
                    continue
                if rec.get("kind") != ESCALATION:
                    continue
                if rec.get("handled"):
                    continue  # 人工/既有处理记录不可覆盖
                rec["handled"] = True
                rec["handled_by"] = AUTO_RESOLVE_BY
                rec["handled_at"] = resolved_at
                rec["resolve_note"] = notes[rec.get("id")]
                changed += 1
            return changed

        return self._mutate(mutate, skip_unchanged=True)

    def close_escalations_for_run(self, admin_run_id: str, resolve_note: str) -> int:
        """关闭某 admin run 名下的全部未处理升级告警（随最终处置闭环）。

        典型场景：AdminMonitor 孤儿看护在处置进行中误判 pending 超时（升级
        escalation 带同 admin_run_id），随后 run 正常完成落最终 disposition——
        误报 escalation 若无人关闭，dashboard 处置卡片永久显示「需人工决策」
        与 result=resolved 矛盾，且 unhandled_for 节流会压制该 spec 后续同型
        告警。仅改写 handled 族字段；已处理条目不可覆盖。返回关闭数量。
        """
        if not admin_run_id:
            return 0
        closed_at = _utcnow_iso()

        def mutate(records):
            changed = 0
            for rec in records:
                if (
                    rec.get("kind") == ESCALATION
                    and not rec.get("handled")
                    and rec.get("admin_run_id") == admin_run_id
                ):
                    rec["handled"] = True
                    rec["handled_by"] = AUTO_RESOLVE_BY
                    rec["handled_at"] = closed_at
                    rec["resolve_note"] = resolve_note
                    changed += 1
            return changed

        return self._mutate(mutate, skip_unchanged=True)

    def latest_signal(
        self, spec: Optional[str], signal_type: str, within_minutes: float
    ) -> Optional[dict]:
        """返回最近一条匹配（spec, signal_type）的记录，供节流判断。

        within_minutes 内存在 → 返回该记录；否则返回 None。
        spec 为 None 时仅匹配 spec=None 的 daemon 级记录（per-spec 记录
        一律跳过，避免污染 daemon 级冷却窗口）。

        窗口锚点 = max(created, last_seen)（admin-signal-consolidation D1）：
        状态沉淀后 created 停在首次触发、同状态续报只刷 last_seen——若仍按
        created 判定窗口，一旦超过 cooldown 便不再命中、节流失效、每轮巡检
        重新唤起 Administrator（比现状更烧钱）。无 last_seen 的历史记录
        （本特性前写入）仍按 created 判定。该 API 有 4 处外部调用点
        （dispatch_stalled / instant_fail_storm / transient_break_storm /
        verify 告警），其窗口语义不变：escalation/disposition 记录不带
        last_seen，仍按 created 判定。
        """
        if within_minutes <= 0:
            return None
        now = time.time()
        cutoff = now - within_minutes * 60
        best = None
        for rec in self.read_all():
            if rec.get("signal_type") != signal_type:
                continue
            if rec.get("kind") not in (SIGNAL, ESCALATION, DISPOSITION, INFO):
                # 四种 kind 已是 admin_alerts.json 全部在册记录（见模块 docstring），
                # 此过滤对正常记录恒放行；保留仅作前瞻性防御，拦截人工修补/
                # 外部工具写入的未知或缺失 kind（code-review c78e3230828e）。
                # evo-reduce-stale-code-selfheal-noise 2.1：INFO 加入白名单——
                # 否则 info 级 stale_code 留痕对 latest_signal 不可见，60 分钟
                # 窗口去重对 info 级整体失效，高频提交下每次 daemon 轮换重启
                # 都重复成条，降噪目标落空。
                continue
            rec_spec = rec.get("spec")
            if spec is not None and rec_spec != spec:
                continue
            if spec is None and rec_spec is not None:
                continue
            # SPEC-B 批③：解析收拢 parse_ts（唯一入口，失败 None 同路 continue）。
            # 存量 created 恒为 aware（_utcnow_iso）；naive 防御分支按唯一策略
            # （本地）解读，原显式 naive→UTC 退役。
            created = parse_ts(rec.get("created") or "")
            if created is None:
                continue
            anchor = created
            last_seen_str = rec.get("last_seen")
            if last_seen_str:
                last_seen = parse_ts(str(last_seen_str))
                if last_seen is not None:
                    anchor = max(created, last_seen)  # 防御：异常数据下取更大者
                # last_seen 不可解析时回退 created（与原 except-pass 同路）
            if anchor.timestamp() < cutoff:
                continue
            if best is None or anchor > best["_anchor"]:
                rec["_anchor"] = anchor
                best = rec
        if best is not None:
            best.pop("_anchor", None)
        return best

    def latest_resolved_disposition(
        self,
        spec: str,
        signal_type: str,
    ) -> Optional[dict]:
        """返回（spec, signal_type）最近一条「成功处置」记录或 None。

        stuck-signal-hygiene D3：仅匹配 kind=DISPOSITION 且 result∈
        {resolved, partially-resolved}——处置成功（根因已修复）后，同信号
        在静默窗口内不复发。

        不复用 latest_signal（fix-latest-resolved-disposition-scope）：后者
        匹配 kind∈{SIGNAL, ESCALATION, DISPOSITION} 且不按 result 过滤，会把
        failed/pending disposition 误当成功处置；且其窗口语义（created 停在
        首次触发）用于静默期会把首见时间误当处置时刻，静默窗口大幅错位。
        本查询返回最近一条匹配记录的**原始 created**（处置时刻 = 记录写入时），
        不计算 last_seen——处置记录不带 last_seen（merge_signal 不作用于
        disposition），created 即处置时刻。

        Args:
            spec: spec 名（必须有值；处置记录恒带 spec，不做 daemon 级匹配）
            signal_type: 信号类型（如 stuck）

        Returns: 匹配记录 dict（含 created，供静默窗口计算）；无匹配返回 None。
        """
        best = None
        for rec in self.read_all():
            if rec.get("kind") != DISPOSITION:
                continue
            if rec.get("signal_type") != signal_type:
                continue
            if rec.get("spec") != spec:
                continue
            if rec.get("result") not in ("resolved", "partially-resolved"):
                continue
            # str(...) 归一与 read_all 同口径：created 非字符串脏形态不抛 TypeError
            if best is None or str(rec.get("created") or "") > str(
                best.get("created") or ""
            ):
                best = rec
        return best

    def unhandled_for(self, spec: Optional[str], signal_type: str) -> Optional[dict]:
        """返回（spec, signal_type）对应的未处理升级告警（若有）。

        Administrator 无法处置升级为人类告警后，同信号不再重复唤起。

        仅匹配 kind=ESCALATION——不匹配 kind=signal（kind=signal 记录的
        未处理判定见 unhandled_signal_for）。
        """
        for rec in self.read_all():
            if rec.get("kind") != ESCALATION or rec.get("handled"):
                continue
            if rec.get("signal_type") != signal_type:
                continue
            rec_spec = rec.get("spec")
            if spec is None and rec_spec is not None:
                continue
            if spec is not None and rec_spec != spec:
                continue
            return rec
        return None

    def unhandled_signal_for(self, spec: Optional[str], signal_type: str) -> Optional[dict]:
        """返回（spec, signal_type）对应的未处理信号记录（若有），供孤儿处置重派判定。

        admin-disposition-reschedule：匹配 kind=SIGNAL ∧ 非 handled ∧
        signal_type 相等 ∧ spec 严格相等 ∧ escalated 为真——返回最新一条
        命中（read_all 已按 created 倒序）。未找到返回 None。

        与 unhandled_for 同结构，但作用于 kind=signal 记录：
        - unhandled_for 匹配 kind=ESCALATION（人工告警去重）
        - unhandled_signal_for 匹配 kind=SIGNAL ∧ escalated=true（底层信号回溯）

        escalated=true 口径：仅在实际唤起 Administrator 时（节流通过）才以
        escalated=true 落信号记录，节流分支落 escalated=False。以 escalated=true
        匹配可避免为「从未唤起过的节流沉淀记录」发起重派。

        spec 严格相等：实测现有信号记录 spec 全部非 None（spec=None 只出现在
        kind=escalation），不做宽松匹配。
        """
        for rec in self.read_all():
            if rec.get("kind") != SIGNAL:
                continue
            if rec.get("handled"):
                continue
            if not rec.get("escalated"):
                continue
            if rec.get("signal_type") != signal_type:
                continue
            rec_spec = rec.get("spec")
            if spec is None and rec_spec is not None:
                continue
            if spec is not None and rec_spec != spec:
                continue
            return rec
        return None

    # ── admin-dispatch-failure-escalation D2 ──────────────────────

    def close_dispatch_failure_alerts(self, spec: str, resolve_note: str) -> int:
        """关闭某 spec 名下未处理的派发失败升级告警。

        admin-dispatch-failure-escalation D2：dispatch 成功（run_administrator
        正常返回）时调用——仅关闭「派发失败」产生的记录（带 next_retry_at
        字段的 kind=escalation 未处理记录，含 admin_dispatch_programming_error
        与原类型两条分流路径）；其他升级记录（人工处置中/其他原因，不带
        next_retry_at）不受影响。resolve_note 恒为「后续派发成功」。
        已处理条目不可覆盖（人工记录不可覆盖）。返回关闭数量。
        """
        if not spec:
            return 0
        resolved_at = _utcnow_iso()

        def mutate(records):
            changed = 0
            for rec in records:
                if rec.get("kind") != ESCALATION or rec.get("handled"):
                    continue
                if rec.get("spec") != spec:
                    continue
                if not rec.get("next_retry_at"):
                    continue  # 非派发失败记录不关
                rec["handled"] = True
                rec["handled_by"] = AUTO_RESOLVE_BY
                rec["handled_at"] = resolved_at
                rec["resolve_note"] = resolve_note
                changed += 1
            return changed

        return self._mutate(mutate, skip_unchanged=True)

    def bump_dispatch_retry(self, alert_id: str, max_retries: int = 1) -> bool:
        """派发重试仍失败 → 既有升级记录 retry_count 递增（上限 max_retries）。

        admin-dispatch-failure-escalation D2：重试不追加新记录，只 bump
        既有记录的 retry_count，达到上限后 _retry_due_dispatch_failures
        不再选中该记录。返回是否实际递增（id 不匹配、非 escalation 或
        已达上限时返回 False）；未发生递增不写回，避免无变更刷新 mtime。
        """

        def mutate(records):
            changed = False
            for rec in records:
                if rec.get("id") != alert_id:
                    continue
                if rec.get("kind") != ESCALATION:
                    continue
                cur = 0
                try:
                    cur = int(rec.get("retry_count") or 0)
                except (TypeError, ValueError):
                    cur = 0
                if cur >= max_retries:
                    continue  # 已达上限：不改动，避免无变更写回
                rec["retry_count"] = min(cur + 1, max_retries)
                changed = True
            return changed

        return self._mutate(mutate, skip_unchanged=True)


class DisputeAuditStore:
    """dispute 裁决审计（add-deliverable-declaration-triage D6 / 4.5）。

    独立 jsonl 文件 ``.fenix/dispute_audits.jsonl``（逐行 JSON，append-only），
    与 admin_alerts.json 分开——judge **自动裁决**不可与人工告警混流。复用
    AdminStore 的 flock 持久化模式（同进程线程锁 + 跨进程文件排他锁）。

    记录字段（design D6）：``spec``、``trigger_run_id``（实现 run）、
    ``judge_run_id``（dispute-judge run）、``verdicts``（裁决 JSON 全文）、
    ``diff``（声明段修正前后），``created``（UTC 时间戳）。人工可复核、
    可回滚（回滚 = 恢复声明段原文 + 触发重派）。
    """

    def __init__(self, project_root, logger=None):
        self.project_root = Path(project_root)
        self.audit_path = self.project_root / ".fenix" / "dispute_audits.jsonl"
        self._lockfile = Path(str(self.audit_path) + ".lock")
        self._thread_lock = threading.Lock()
        self._logger = logger

    def append(self, entry: dict) -> None:
        """追加一条审计记录（排他锁内 append + flush + fsync）。入口字段就地补齐。"""
        # kind/created 为审计默认值，不接受入口覆盖：created 须反映实际落盘
        # 时刻（复用内存 dict 转写携带旧时间戳不得穿透审计语义）
        rec = dict(entry or {})
        rec["kind"] = "dispute-audit"
        rec["created"] = _utcnow_iso()
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        with self._thread_lock:
            with self._lockfile.open("w", encoding="utf-8") as lf:
                fcntl.flock(lf, fcntl.LOCK_EX)
                try:
                    with self.audit_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        f.flush()
                        # 与 AdminStore._write_unlocked 对齐：落盘后才返回，
                        # 崩溃时最近一条审计记录不因页缓存未刷而丢失
                        os.fsync(f.fileno())
                    self._trim_unlocked()
                finally:
                    fcntl.flock(lf, fcntl.LOCK_UN)

    def _trim_unlocked(self) -> None:
        """写回前裁剪到最近 MAX_AUDIT_RECORDS 条（调用方须已持有排他锁）。

        jsonl 是追加写，无法像 AdminStore 在内存数组里删头，超限时整文件
        读入、保留末尾 N 行（含刚追加的最新一条），经临时文件 + rename
        原子替换，中途崩溃不丢既有审计。裁剪幂等：未超限不做任何写动作。
        """
        try:
            lines = self.audit_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return
        lines = [ln for ln in lines if ln.strip()]
        if len(lines) <= MAX_AUDIT_RECORDS:
            return
        fd, tmp_str = tempfile.mkstemp(
            prefix=".dispute_audits.",
            suffix=".tmp",
            dir=str(self.audit_path.parent),
        )
        tmp_path = Path(tmp_str)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for ln in lines[-MAX_AUDIT_RECORDS:]:
                    f.write(ln + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.rename(str(tmp_path), str(self.audit_path))
            _fsync_parent_dir(self.audit_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def read_all(self) -> list:
        """读取全部审计记录（最新的在前）。损坏/缺失返回空列表。

        与 append 一致在 _thread_lock + flock 排他锁内读取：单条记录
        （verdicts 全文 + diff）可能超出单次 write 原子性，无锁并发读会
        观察到半行 JSON 而被下方 JSONDecodeError 静默跳过。
        """
        if not self.audit_path.exists():
            return []
        out: list = []
        try:
            with self._thread_lock:
                with self._lockfile.open("w", encoding="utf-8") as lf:
                    fcntl.flock(lf, fcntl.LOCK_EX)
                    try:
                        with self.audit_path.open(encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    d = json.loads(line)
                                except json.JSONDecodeError:
                                    continue
                                if isinstance(d, dict):
                                    out.append(d)
                    finally:
                        fcntl.flock(lf, fcntl.LOCK_UN)
        except (OSError, UnicodeDecodeError):
            return []
        # str(...) or ""：对 "created" 非字符串脏形态（null/数字等）设防，
        # 避免 None/int 与 str 混排抛 TypeError
        out.sort(key=lambda e: str(e.get("created") or ""), reverse=True)
        return out
