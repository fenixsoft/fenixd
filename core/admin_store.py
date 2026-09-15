"""
admin_store.py — Administrator 告警/处置记录持久化（.fenix/admin_alerts.json）。

统一存三类记录（append-only JSON 数组，同文件）：
  - kind="signal"      监视器检测到的困境信号（审计 + 节流依据）
  - kind="escalation"  需人工介入的升级告警（未处理时 Dashboard 横幅展示）
  - kind="disposition" Administrator 完成的一次处置记录

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

# 记录种类
SIGNAL = "signal"
ESCALATION = "escalation"
DISPOSITION = "disposition"

# 记录数上限（2026-09-01 用户决策）：任何写回时自动裁剪，只保留最近 150 条。
# 消费方（latest_signal 冷却去重、auto_resolve 按 id 闭环）均只依赖近期记录，
# 裁掉最旧历史不影响语义。
MAX_RECORDS = 150

# 降噪分级（2026-09-01 用户决策）：只有 critical/major 默认进人工待处理
# 队列；warning/minor 写入即自动标记已处理（仍留历史记录，不弹横幅）。
HUMAN_SEVERITIES = ("critical", "major")


def severity_needs_human(severity: str) -> bool:
    return (severity or "").lower() in HUMAN_SEVERITIES


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AdminStore:
    """读写 .fenix/admin_alerts.json 的存储层。

    线程/进程安全：追加与标记已处理均在 flock 排他锁内完成读-改-写；
    写入用临时文件 + rename 保证原子性，崩溃不损坏既有记录。
    """

    def __init__(self, project_root, logger=None):
        self.project_root = Path(project_root)
        self.alerts_path = self.project_root / ".fenix" / "admin_alerts.json"
        self._lockfile = Path(str(self.alerts_path) + ".lock")
        self._thread_lock = threading.Lock()  # 进程内互斥（跨线程）
        self._logger = logger

    # ── 内部：加锁读/写 ───────────────────────────────────────────

    def _lock(self):
        self._lockfile.parent.mkdir(parents=True, exist_ok=True)
        return open(self._lockfile, "w")

    @staticmethod
    def _read_unlocked(path: Path) -> list:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        return [e for e in data if isinstance(e, dict)]

    def _read_locked(self) -> list:
        with self._lock() as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                return self._read_unlocked(self.alerts_path)
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
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _mutate(self, fn, skip_unchanged: bool = False):
        """在单次排他锁内完成读-改-写，返回 fn(records) 的结果。

        跨进程并发（监视线程 append 与 Dashboard mark_handled）若分别在两次
        锁获取中读改写会互相覆盖丢失记录，因此必须一次性持锁完成。
        skip_unchanged=True 时（add-alert-auto-resolve D1）：fn 返回假值
        （无任何变更）则跳过写回，文件 mtime 保持不变。

        写回前自动裁剪到最近 MAX_RECORDS 条（新记录在数组末尾，删头部最旧的）。
        """
        with self._thread_lock:
            with self._lock() as lf:
                fcntl.flock(lf, fcntl.LOCK_EX)
                try:
                    records = self._read_unlocked(self.alerts_path)
                    result = fn(records)
                    if skip_unchanged and not result:
                        return result
                    if len(records) > MAX_RECORDS:
                        del records[:-MAX_RECORDS]
                    self._write_unlocked(records)
                    return result
                finally:
                    fcntl.flock(lf, fcntl.LOCK_UN)

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
        return rec

    def append(self, entry: dict) -> dict:
        """追加一条记录，补齐 id/created/handled 等默认字段，返回落地后的记录。

        记录顺序：新记录追加到数组末尾（最近在后）。读侧按倒序返回。
        """
        rec = self._normalize_entry(entry)
        self._mutate(lambda records: records.append(rec))
        return rec

    def merge_signal(self, entry: dict, status_hash: str):
        """沉淀式写入 per-spec 检测信号（admin-signal-consolidation D1）。

        同一 (spec, signal_type, status_hash) 视为「状态未变」：不新增记录、
        仅刷新 last_seen（合并），返回既有记录与 (record, is_new=False)；
        状态变化 / 首见时创建新记录并携带 status_hash / last_seen，
        返回 (record, is_new=True)。

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

        return self._mutate(mutate)

    def read_all(self) -> list:
        """读取全部记录（最新的在前）。损坏/缺失返回空列表。"""
        records = self._read_locked()
        records.sort(key=lambda e: e.get("created", ""), reverse=True)
        return records

    def unhandled(self) -> list:
        """未处理的升级告警（kind=escalation 且未 handled），最新的在前。"""
        return [
            e for e in self.read_all()
            if e.get("kind") == ESCALATION and not e.get("handled")
        ]

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
        return self._mutate(mutate)

    def mark_escalated(self, alert_id: str) -> bool:
        """将某条信号标记为已唤起 Administrator（escalated=True）。

        供「写入即待唤起」型信号（family_explosion：pm_engine 直接落库、由
        AdminMonitor 摄取唤起）去重使用：同记录只唤起一次。
        返回是否找到并更新。
        """
        def mutate(records):
            changed = False
            for rec in records:
                if rec.get("id") == alert_id:
                    if not rec.get("escalated"):
                        rec["escalated"] = True
                        changed = True
            return changed
        return self._mutate(mutate)

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
        return self._mutate(mutate)

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
        notes = {r.get("id"): r.get("resolve_note") or ""
                 for r in resolutions or [] if r.get("id")}
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
                if (rec.get("kind") == ESCALATION and not rec.get("handled")
                        and rec.get("admin_run_id") == admin_run_id):
                    rec["handled"] = True
                    rec["handled_by"] = AUTO_RESOLVE_BY
                    rec["handled_at"] = closed_at
                    rec["resolve_note"] = resolve_note
                    changed += 1
            return changed
        return self._mutate(mutate, skip_unchanged=True)

    def latest_signal(self, spec: Optional[str], signal_type: str,
                      within_minutes: float) -> Optional[dict]:
        """返回最近一条匹配（spec, signal_type）的记录，供节流判断。

        within_minutes 内存在 → 返回该记录；否则返回 None。
        spec 为 None 时匹配所有 spec（用于 daemon 级信号）。

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
            if rec.get("kind") not in (SIGNAL, ESCALATION, DISPOSITION):
                continue
            rec_spec = rec.get("spec")
            if spec is not None and rec_spec != spec:
                continue
            if spec is None and rec_spec is not None:
                continue
            try:
                created = datetime.fromisoformat(
                    (rec.get("created") or "").replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                continue
            anchor = created
            last_seen_str = rec.get("last_seen")
            if last_seen_str:
                try:
                    last_seen = datetime.fromisoformat(
                        str(last_seen_str).replace("Z", "+00:00")
                    )
                    anchor = max(created, last_seen)  # 防御：异常数据下取更大者
                except (ValueError, TypeError):
                    pass  # last_seen 不可解析时回退 created
            if anchor.timestamp() < cutoff:
                continue
            if best is None or anchor > best["_anchor"]:
                rec["_anchor"] = anchor
                best = rec
        if best is not None:
            best.pop("_anchor", None)
        return best

    def unhandled_for(self, spec: Optional[str], signal_type: str) -> Optional[dict]:
        """返回（spec, signal_type）对应的未处理升级告警（若有）。

        Administrator 无法处置升级为人类告警后，同信号不再重复唤起。
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
        """追加一条审计记录（排他锁内 append + flush）。入口字段就地补齐。"""
        rec = {"kind": "dispute-audit", "created": _utcnow_iso()}
        rec.update(entry or {})
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
                finally:
                    fcntl.flock(lf, fcntl.LOCK_UN)

    def read_all(self) -> list:
        """读取全部审计记录（最新的在前）。损坏/缺失返回空列表。"""
        if not self.audit_path.exists():
            return []
        out: list = []
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
        except OSError:
            return []
        out.sort(key=lambda e: e.get("created", ""), reverse=True)
        return out
