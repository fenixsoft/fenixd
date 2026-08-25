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

# 记录种类
SIGNAL = "signal"
ESCALATION = "escalation"
DISPOSITION = "disposition"


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

    def _mutate(self, fn):
        """在单次排他锁内完成读-改-写，返回 fn(records) 的结果。

        跨进程并发（监视线程 append 与 Dashboard mark_handled）若分别在两次
        锁获取中读改写会互相覆盖丢失记录，因此必须一次性持锁完成。
        """
        with self._thread_lock:
            with self._lock() as lf:
                fcntl.flock(lf, fcntl.LOCK_EX)
                try:
                    records = self._read_unlocked(self.alerts_path)
                    result = fn(records)
                    self._write_unlocked(records)
                    return result
                finally:
                    fcntl.flock(lf, fcntl.LOCK_UN)

    # ── 公开 API ─────────────────────────────────────────────────

    def append(self, entry: dict) -> dict:
        """追加一条记录，补齐 id/created/handled 等默认字段，返回落地后的记录。

        记录顺序：新记录追加到数组末尾（最近在后）。读侧按倒序返回。
        """
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

        self._mutate(lambda records: records.append(rec))
        return rec

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

    def latest_signal(self, spec: Optional[str], signal_type: str,
                      within_minutes: float) -> Optional[dict]:
        """返回最近一条匹配（spec, signal_type）的记录，供节流判断。

        within_minutes 内存在 → 返回该记录；否则返回 None。
        spec 为 None 时匹配所有 spec（用于 daemon 级信号）。
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
            if created.timestamp() < cutoff:
                continue
            if best is None or created > best["_created"]:
                rec["_created"] = created
                best = rec
        if best is not None:
            best.pop("_created", None)
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
