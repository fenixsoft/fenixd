"""core/pm_engine/escalation_chain.py — 升级信号处置链派发器
（add-escalation-chain-admin-arbiter）。

把「升级边默认直达人工」反转为「默认走自动化处置链」：升级边信号
（freeze_for_human 全族与 _send_human_escalation_alert 全部调用点）默认入链，
链序固定 **Admin（受限环境运维）→ Arbiter（全局拍板）→ 人工**；链内任一级
处置成功即闭环（信号收口 + spec 显式解冻），人工队列零痕迹；仅链终点
（Arbiter 失败/配额耗尽/黑名单/降级态）产生人工告警。

设计真相源：spec/changes/add-escalation-chain-admin-arbiter/design.md
（决策 1 链派发器独立成模块——事件驱动直派，不走 admin_monitor 5 分钟
巡检；决策 2 配额状态独立 state 文件；决策 5 上升件=链终点专属落盘路径）。

模块职责：
- 链入口判定（防自环）：只收框架/runner 侧产生的信号；链成员的处置输出
  永远是链内转单边（Admin 超范围→Arbiter、处置失败→下一级），MUST NOT
  作为新信号重新入链（生产注入点只有 family._send_human_escalation_alert
  咽喉与 freeze_for_human 咽喉，链内转单走进程内直调，不经咽喉）。
- 双咽喉改道：state_machine.freeze_for_human 咽喉经 ``arbiter.install_freeze_hook``
  注册的回调链头优先派发（链不可用回落既有 Arbiter 直派）；family 咽喉在
  告警落盘**之前**调 :meth:`EscalationChain.submit_entry`——链接单时零
  admin_alerts 落盘、零 pending、零推送。
- 黑名单 kill switch：``chain.blacklist`` 配置内的信号绕过全链直达人工
  队列（写入即按降级态降噪分级标记 handled 的既有语义保留）。初始空集。
- 链级失能 fail-open：``arbiter.enabled=false`` 或链装配缺席（runner/
  state_machine 未注入等配置性缺失）时整体退回现状行为（升级边直达人工
  队列 + narrative 补叙），一次性 WARN 留痕（每进程一次，不逐件刷屏）；
  配置修复后自动恢复入链（无需人工干预）。
- 双车道配额：Admin 尝试配额与 Arbiter 复现配额（2 次/签名缺省），状态
  持久化在 ``.fenix/escalation_chain_state.json``（决策 2——计数是状态不是
  台账事实）；复位窗 7 天无复现清零、spec 状态迁移清零；dead-man/停机类
  签名维持永久单次（例外不复位）。
- 签名单源：spec 归属非空复用 ``arbiter_failure_signature``；spec=null 信号
  签名含主体键（从信号 payload 提取：蒸馏欠账归档名/triage 场景集指纹等），
  提取不到退化类型级并在台账标注粒度。
- 兜底看护（design 决策 1）：链在办件登记进状态文件 ``in_flight`` 区，
  admin_monitor 周期巡检经 :meth:`EscalationChain.reap_stale_inflight` 消费
  （pending 超时升级语义不变——链派发的 admin run 沿用 run_administrator
  的 pending disposition 落盘，daemon 重启后的孤儿接管与既有路径同一套）。
"""

from __future__ import annotations

import json
import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# 日志组件名（logger.warning(component, message) 口径）
COMPONENT = "pm_engine.escalation_chain"

# 配额状态文件（.fenix/escalation_chain_state.json，gitignored 运行时文件；
# 决策 2：主树运行时写入仅 daemon 做，实现分支只交付读写层）
CHAIN_STATE_FILENAME = "escalation_chain_state.json"
# 状态文件 schema 版本（结构变更时递增；读侧按版本兼容）
CHAIN_STATE_VERSION = 1
# 存量迁移版本哨兵（task 4.2：升版即重跑一次迁移）
CHAIN_MIGRATION_VERSION = 1

# 单飞队列深度上限（对齐 arbiter lane 形态；满队列显式报错不吞 conflict）
CHAIN_QUEUE_MAX = 8

# 链在办件看护：in_flight 条目超时（秒）——超过即视为 chain worker 死亡残留，
# 巡检消费时清除并告警（pending disposition 记录的孤儿接管由 admin_monitor
# 既有 _recover_orphaned_dispositions 承接，语义不变）
CHAIN_INFLIGHT_STALE_S = 6 * 3600

# dead-man 永久单次的台账 kind（例外不复位——spec「dead-man/停机类签名维持
# 永久单次、不适用复位」）
DEADMAN_LEDGER_KINDS = frozenset({"dead-man"})

# spec=null 主体键提取的 payload 键优先级（spec「从信号 payload 提取，如蒸馏
# 欠账归档名、triage 场景集指纹」）。首个非空字符串命中即主体键；全脱靶退化
# 类型级（granularity=type，台账标注）。
_SUBJECT_KEY_PRIORITY = (
    "subject",
    "subject_key",
    "fingerprint",
    "archive",
    "archive_name",
    "scenario_set",
    "scenario_fingerprint",
    "topic",
    "signal_id",
)

# 主体键缺失时的类型级占位（签名退化为 <signal>::_type_level_）
_TYPE_LEVEL_SUBJECT = "_type_level_"


def chain_state_path(project_root) -> Path:
    """配额状态文件路径（.fenix/escalation_chain_state.json）。"""
    return Path(project_root) / ".fenix" / CHAIN_STATE_FILENAME


def load_chain_state(project_root) -> dict:
    """读全量链状态（fail-open：缺失/损坏/版本不识别一律回空骨架）。"""
    path = chain_state_path(project_root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty_state()
    if not isinstance(raw, dict) or raw.get("version") != CHAIN_STATE_VERSION:
        return _empty_state()
    state = _empty_state()
    sigs = raw.get("signatures")
    if isinstance(sigs, dict):
        state["signatures"] = {
            str(k): dict(v) for k, v in sigs.items() if isinstance(v, dict)
        }
    meta = raw.get("meta")
    if isinstance(meta, dict):
        state["meta"] = dict(meta)
    inflight = raw.get("in_flight")
    if isinstance(inflight, list):
        state["in_flight"] = [dict(x) for x in inflight if isinstance(x, dict)]
    return state


def _empty_state() -> dict:
    return {
        "version": CHAIN_STATE_VERSION,
        "signatures": {},   # sig -> {admin_attempts, arbiter_rulings, last_seen, last_spec_status}
        "meta": {},         # {migration_version, migrated_at, ...}
        "in_flight": [],    # [{chain_id, signature, spec, phase, started_at}]
    }


def save_chain_state(project_root, state: dict) -> bool:
    """原子写链状态（mkstemp + os.replace；写失败 False 由调用方降级）。"""
    import os
    import tempfile

    path = chain_state_path(project_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(state)
        payload["version"] = CHAIN_STATE_VERSION
        payload["updated_at"] = _utcnow_iso()
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{CHAIN_STATE_FILENAME}.", suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, str(path))
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
        return True
    except OSError:
        return False


def subject_key_from_payload(payload: Optional[dict]) -> tuple:
    """spec=null 信号的主体键提取（返回 (subject, granularity)）。

    按 _SUBJECT_KEY_PRIORITY 从 payload 提取首个非空字符串值；提取不到
    退化类型级（granularity="type"）——调用方须在台账标注粒度（spec 硬约束）。
    """
    if isinstance(payload, dict):
        for key in _SUBJECT_KEY_PRIORITY:
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()[:120], "subject"
            # 结构化指纹类值（dict 带 name/id）取其可读标识
            if isinstance(val, dict):
                inner = val.get("name") or val.get("id") or val.get("fingerprint")
                if isinstance(inner, str) and inner.strip():
                    return inner.strip()[:120], "subject"
    return _TYPE_LEVEL_SUBJECT, "type"


def chain_signature(spec: str, signal_type: str, payload: Optional[dict] = None) -> tuple:
    """链签名（dedup/配额键单源）：返回 (signature, granularity)。

    spec 归属非空：复用 ``arbiter_failure_signature``（``<spec>::<signal>``，
    双咽喉同签名 dedup 语义不变）；spec=null 信号：``<signal>::<主体键>``，
    主体键提取不到退化类型级（granularity="type"——台账标注用）。
    """
    from core.pm_engine.arbiter import arbiter_failure_signature

    sig_type = (signal_type or "unknown").strip()
    if (spec or "").strip() and spec != "global":
        return arbiter_failure_signature(spec, sig_type), "spec"
    subject, granularity = subject_key_from_payload(payload)
    if granularity == "type":
        return arbiter_failure_signature("global", sig_type), "type"
    return arbiter_failure_signature(f"null:{subject}", sig_type), "subject"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_since(ts_iso: str, now: Optional[datetime] = None) -> Optional[float]:
    try:
        then = datetime.fromisoformat(str(ts_iso))
    except (TypeError, ValueError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - then).total_seconds() / 86400.0


class ChainQuotaStore:
    """双车道配额状态读写层（task 1.4；.fenix/escalation_chain_state.json）。

    计数是状态不是台账事实（决策 2）——不入 arbiter ledger；跨重启有效。
    每次变更全量重读改写（状态文件小，且触发频率=升级边信号频率，低频）；
    锁内串行化本进程并发写者。
    """

    def __init__(self, project_root, logger=None):
        self.project_root = Path(project_root)
        self.logger = logger
        self._lock = threading.Lock()

    # ── 配置读取（热更新：每次判定即时解析）─────────────────────────

    def quota_config(self) -> dict:
        try:
            from core.config import ConfigLoader

            raw = ConfigLoader.resolve_config(self.project_root)
            return ConfigLoader.get_chain_config(raw)
        except Exception:
            return {
                "admin_attempts": 2,
                "arbiter_rulings": 2,
                "reset_window_days": 7,
                "blacklist": [],
            }

    # ── 基础读写 ────────────────────────────────────────────────────

    def _mutate(self, fn):
        """锁内 读→改→写（fn(state) 原地修改；写失败不抛由调用方降级）。"""
        with self._lock:
            state = load_chain_state(self.project_root)
            result = fn(state)
            save_chain_state(self.project_root, state)
            return result

    def entry(self, sig: str) -> dict:
        state = load_chain_state(self.project_root)
        return dict(state["signatures"].get(sig) or {})

    def admin_attempts(self, sig: str) -> int:
        return int(self.entry(sig).get("admin_attempts") or 0)

    def arbiter_rulings(self, sig: str) -> int:
        return int(self.entry(sig).get("arbiter_rulings") or 0)

    # ── 计数与复位 ──────────────────────────────────────────────────

    def count_admin_attempt(self, sig: str) -> int:
        """Admin 失败尝试计一次（run 崩溃/超时/终态失败；超范围转单不计）。"""
        def _inc(state):
            ent = state["signatures"].setdefault(
                sig, {"admin_attempts": 0, "arbiter_rulings": 0}
            )
            ent["admin_attempts"] = int(ent.get("admin_attempts") or 0) + 1
            ent["last_seen"] = _utcnow_iso()
            return ent["admin_attempts"]

        return self._mutate(_inc) or 0

    def count_arbiter_ruling(self, sig: str) -> int:
        """Arbiter 拍板计一次（处置成功落账；复现配额判定消费）。"""
        def _inc(state):
            ent = state["signatures"].setdefault(
                sig, {"admin_attempts": 0, "arbiter_rulings": 0}
            )
            ent["arbiter_rulings"] = int(ent.get("arbiter_rulings") or 0) + 1
            ent["last_seen"] = _utcnow_iso()
            return ent["arbiter_rulings"]

        return self._mutate(_inc) or 0

    def observe_spec_status(self, sig: str, spec_status: str) -> bool:
        """状态迁移复位（spec「或该 spec 状态发生迁移清零」）。

        记录 last_spec_status；与上次观测值不同（且双方非空）→ 配额清零并
        返回 True。首见只落基线不复位（避免首轮触发误清）。
        """
        def _obs(state):
            ent = state["signatures"].setdefault(
                sig, {"admin_attempts": 0, "arbiter_rulings": 0}
            )
            prev = str(ent.get("last_spec_status") or "")
            cur = str(spec_status or "")
            ent["last_spec_status"] = cur
            if prev and cur and prev != cur:
                ent["admin_attempts"] = 0
                ent["arbiter_rulings"] = 0
                ent["reset_cause"] = "spec-transition"
                ent["reset_at"] = _utcnow_iso()
                return True
            return False

        return bool(self._mutate(_obs))

    def apply_window_reset(self, sig: str, window_days: int) -> bool:
        """复位窗清零（签名连续 window_days 天无复现 → 配额清零）。"""
        def _reset(state):
            ent = state["signatures"].get(sig)
            if not isinstance(ent, dict):
                return False
            last = str(ent.get("last_seen") or "")
            if not last:
                return False
            idle = _days_since(last)
            if idle is not None and idle >= float(window_days) and (
                int(ent.get("admin_attempts") or 0) > 0
                or int(ent.get("arbiter_rulings") or 0) > 0
            ):
                ent["admin_attempts"] = 0
                ent["arbiter_rulings"] = 0
                ent["reset_cause"] = "window"
                ent["reset_at"] = _utcnow_iso()
                return True
            return False

        return bool(self._mutate(_reset))

    def touch(self, sig: str) -> None:
        """复现时刻刷新 last_seen（复位窗计时锚点）。"""
        def _touch(state):
            ent = state["signatures"].setdefault(
                sig, {"admin_attempts": 0, "arbiter_rulings": 0}
            )
            ent["last_seen"] = _utcnow_iso()

        self._mutate(_touch)

    def snapshot(self) -> dict:
        """只读快照（dashboard 配额水位消费）：sig → 计数条目。"""
        state = load_chain_state(self.project_root)
        return {k: dict(v) for k, v in state["signatures"].items()}

    # ── 链在办件登记（design 决策 1：admin_monitor 兜底看护对象）────

    def mark_in_flight(self, chain_id: str, sig: str, spec: str, phase: str):
        def _add(state):
            state["in_flight"] = [
                x for x in state["in_flight"] if x.get("chain_id") != chain_id
            ]
            state["in_flight"].append(
                {
                    "chain_id": chain_id,
                    "signature": sig,
                    "spec": spec,
                    "phase": phase,
                    "started_at": _utcnow_iso(),
                }
            )
            # 在办登记有界（防 worker 崩溃残留无界累积）
            del state["in_flight"][:-32]

        self._mutate(_add)

    def clear_in_flight(self, chain_id: str):
        def _drop(state):
            state["in_flight"] = [
                x for x in state["in_flight"] if x.get("chain_id") != chain_id
            ]

        self._mutate(_drop)

    def stale_in_flight(self, stale_s: float = CHAIN_INFLIGHT_STALE_S) -> list:
        """超时在办件（巡检消费：admin_monitor 看护对象扩展全链在办件）。"""
        state = load_chain_state(self.project_root)
        out = []
        for item in state["in_flight"]:
            idle = _days_since(str(item.get("started_at") or ""))
            if idle is None or idle * 86400.0 >= stale_s:
                out.append(item)
        return out


# ── 迁移哨兵（task 4.2）─────────────────────────────────────────────────

def migration_done(project_root) -> bool:
    state = load_chain_state(project_root)
    return int(state["meta"].get("migration_version") or 0) >= CHAIN_MIGRATION_VERSION


def mark_migration_done(project_root, summary: dict) -> None:
    def _mark(state):
        state["meta"]["migration_version"] = CHAIN_MIGRATION_VERSION
        state["meta"]["migrated_at"] = _utcnow_iso()
        state["meta"]["migration_summary"] = summary

    quota = ChainQuotaStore(project_root)
    quota._mutate(_mark)


# ── 链级派发器 ──────────────────────────────────────────────────────────

class EscalationChain:
    """处置链单例（每项目一个）：入口判定 / dedup / 单飞队列 / 双车道配额。

    生命周期：family 咽喉/引擎装配惰性建（:func:`get_chain`）；runner 与
    state_machine 注入对齐 ArbiterLane（:meth:`set_runner`/:meth:`set_state_
    machine`，engine.py 装配点接线）；worker 线程懒启动（daemon 线程）。
    测试经 :func:`set_chain`/：func:`reset_chain` 操纵单例。
    """

    def __init__(self, project_root, logger=None):
        self.project_root = Path(project_root)
        self.logger = logger
        self._lock = threading.RLock()
        self._queue: "queue.Queue[dict]" = queue.Queue(maxsize=CHAIN_QUEUE_MAX)
        self._worker: Optional[threading.Thread] = None
        # 在飞/排队签名（双咽喉 dedup：同签名只派发一次）
        self._active: set = set()
        # 链级失能一次性 WARN 哨兵（每进程一次；恢复入链后复位于下次失能前
        # 不再刷屏——重新失能的 WARN 由下一次进程生命周期承载）
        self._disabled_warned = False
        # 依赖注入（engine.py 装配点）
        self._runner_ref = None
        self._state_machine_ref = None
        self._quota = ChainQuotaStore(project_root, logger)

    # ── 装配注入 ────────────────────────────────────────────────────

    def set_runner(self, runner):
        self._runner_ref = runner

    def set_state_machine(self, sm):
        self._state_machine_ref = sm

    def _resolve_runner(self):
        runner = getattr(self, "_runner_ref", None)
        if runner is not None:
            return runner
        # 引擎装配缺席时惰性借道 arbiter lane 单例（同进程装配先后无关）
        try:
            from core.pm_engine.arbiter import get_lane

            lane = get_lane()
            return lane._resolve_runner() if lane is not None else None
        except Exception:
            return None

    def _resolve_state_machine(self):
        sm = getattr(self, "_state_machine_ref", None)
        if sm is not None:
            return sm
        try:
            from core.pm_engine.arbiter import get_lane

            lane = get_lane()
            return lane._resolve_state_machine() if lane is not None else None
        except Exception:
            return None

    # ── 配置与可用性判定 ────────────────────────────────────────────

    def config(self) -> dict:
        return self._quota.quota_config()

    def blacklisted(self, signal_type: str) -> bool:
        """黑名单 kill switch 判定（名单内信号绕过全链直达人工队列）。"""
        sig = (signal_type or "").strip()
        return sig in set(self.config().get("blacklist") or [])

    def chain_active(self) -> bool:
        """链级可用判定（fail-open 闸门）。

        可用 = arbiter.enabled（链总开关，关闭态零侵扰）∧ 车道装配完备
        （runner + state_machine——spawn 失能/装配缺失属配置性问题，非单件
        失败）。不可用时调用方整体退回现状行为（直达人工 + narrative）。
        """
        try:
            from core.pm_engine.arbiter import get_lane

            lane = get_lane(self.project_root, self.logger)
            if lane is None or not lane.enabled:
                return False
        except Exception:
            return False
        return self._resolve_runner() is not None and (
            self._resolve_state_machine() is not None
        )

    def _warn_disabled_once(self, reason: str):
        if self._disabled_warned:
            return
        self._disabled_warned = True
        self._log(
            "warning",
            f"处置链级失能（一次性 WARN，fail-open 直达人工）: {reason}",
        )

    def _log(self, level: str, message: str, context: Optional[dict] = None):
        log = getattr(self, "logger", None)
        if log is None:
            return
        try:
            getattr(log, level)(COMPONENT, message, context or None)
        except TypeError:
            getattr(log, level)(COMPONENT, message)
        except Exception:
            pass

    # ── 触发面入口（双咽喉共用）─────────────────────────────────────

    def submit_entry(
        self,
        *,
        spec: str,
        signal_type: str,
        severity: str = "major",
        description: str = "",
        evidence: str = "",
        recommended_action: str = "",
        trigger: Optional[dict] = None,
        payload: Optional[dict] = None,
        source: str = "",
    ) -> str:
        """链头派发入口（family 咽喉在告警落盘前调用）。返回处置字：

        - ``"queued"``：已入链单飞队列（调用方 MUST NOT 落人工告警——链内
          成功零人工感知，终点失败由链回调写入上升件）；
        - ``"deduped"``：同签名已在飞/排队（同上，不落盘）；
        - ``"blacklisted"``：kill switch 命中（调用方走既有落盘路径）；
        - ``"disabled"``：链级失能/关闭（调用方走既有落盘路径，一次性 WARN
          已留痕）。

        排队登记失败（队列满）抛 RuntimeError——调用方回落既有路径，MUST
        NOT 报假成功。
        """
        if self.blacklisted(signal_type):
            self._log("info", f"黑名单信号绕过处置链直达人工: {signal_type}")
            return "blacklisted"
        if not self.chain_active():
            self._warn_disabled_once(
                "arbiter.enabled=false 或链装配缺席（runner/state_machine 缺失）"
            )
            return "disabled"
        sig, granularity = chain_signature(spec, signal_type, payload)
        with self._lock:
            if sig in self._active:
                self._log("info", f"处置链 dedup（同签名在飞/排队）: sig={sig}")
                return "deduped"
            item = {
                "spec": str(spec or ""),
                "signal_type": str(signal_type or ""),
                "severity": str(severity or "major"),
                "description": str(description or ""),
                "evidence": str(evidence or ""),
                "recommended_action": str(recommended_action or ""),
                "trigger": dict(trigger or {}),
                "payload": dict(payload or {}),
                "signature": sig,
                "granularity": granularity,
                "source": source,
                "enqueued_at": _utcnow_iso(),
            }
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                raise RuntimeError(
                    f"处置链单飞队列已满（maxsize={CHAIN_QUEUE_MAX}），"
                    f"触发登记失败 spec={spec} signal={signal_type}"
                )
            self._active.add(sig)
        self._ensure_worker()
        self._log(
            "info",
            f"升级信号入处置链（链头 Admin）: sig={sig} granularity={granularity} "
            f"source={source}",
        )
        return "queued"

    # ── worker（链单飞串行消费）─────────────────────────────────────

    def _ensure_worker(self):
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._worker_loop,
                daemon=True,
                name="escalation-chain-worker",
            )
            self._worker.start()

    def _worker_loop(self):
        while True:
            try:
                item = self._queue.get()
            except Exception:  # pragma: no cover - 病态
                continue
            try:
                self._process(item)
            except Exception as e:
                # 单件处理崩溃不杀 worker；签名释放允许后续触发重新入链
                self._log("error", f"处置链处理异常（继续下一件）: {e}")
            finally:
                with self._lock:
                    self._active.discard(str(item.get("signature") or ""))
                try:
                    self._queue.task_done()
                except Exception:
                    pass

    # ── 主流程：配额闸门 → Admin → Arbiter → 终点 ───────────────────

    def _process(self, item: dict):
        spec = str(item.get("spec") or "")
        sig = str(item.get("signature") or "")
        chain_id = f"chain-{int(time.time() * 1000)}"
        item["chain_id"] = chain_id
        quota_cfg = self.config()
        window_days = int(quota_cfg.get("reset_window_days") or 7)

        # 复现登记与配额复位（复位窗 / spec 状态迁移清零；dead-man 例外不复位）
        self._quota.touch(sig)
        self._quota.apply_window_reset(sig, window_days)
        sm = self._resolve_state_machine()
        if sm is not None and spec and spec != "global":
            try:
                status = str((sm.read_one(spec) or {}).get("status") or "")
                if status:
                    self._quota.observe_spec_status(sig, status)
            except Exception:
                pass

        # dead-man 永久例外：曾死人开关停机的签名不再入链，直接上升人工
        if self._deadmanned(sig):
            self._log("warning", f"dead-man 签名触发（永久单次例外）: sig={sig}")
            self._endpoint_escalate(
                item,
                reason="dead-man 永久单次例外（此前同签名已停机，不再自主处置）",
                endpoint_kind="dead-man-permanent",
            )
            return

        self._quota.mark_in_flight(chain_id, sig, spec, "admin")
        admin_trail, phase = self._run_admin_phase(item, quota_cfg)
        self._quota.clear_in_flight(chain_id)
        if phase == "closed":
            return  # Admin 处置成功闭环（side-effects 已在 _run_admin_phase 落）
        if phase == "deferred":
            # 同 spec 在飞 admin run（互斥守卫命中）：本件让行，不双派。
            # 信号若复发由下一次触发重新入链。
            self._log(
                "info",
                f"处置链让行（同 spec 在飞 admin run）: sig={sig}",
            )
            return

        # Arbiter 级配额闸门（复现配额耗尽 → 强制上升人工，task 3.3）
        rulings = self._quota.arbiter_rulings(sig)
        arb_quota = int(quota_cfg.get("arbiter_rulings") or 2)
        if rulings >= arb_quota:
            self._log(
                "warning",
                f"Arbiter 复现配额耗尽（{rulings}/{arb_quota}）强制上升人工: sig={sig}",
            )
            self._write_chain_event(
                item,
                kind="chain-recurrence",
                action_or_upgrade=(
                    f"复现配额耗尽（已拍板 {rulings}/{arb_quota}），第 "
                    f"{rulings + 1} 次复现强制上升人工（granularity="
                    f"{item.get('granularity')}）"
                ),
            )
            self._endpoint_escalate(
                item,
                reason=(
                    f"Arbiter 复现配额耗尽（拍板 {rulings}/{arb_quota} 后第 "
                    f"{rulings + 1} 次复现）"
                ),
                endpoint_kind="quota-exhausted",
                admin_trail=admin_trail,
            )
            return

        self._quota.mark_in_flight(chain_id, sig, spec, "arbiter")
        outcome = self._run_arbiter_phase(item, admin_trail, quota_cfg)
        self._quota.clear_in_flight(chain_id)
        if outcome == "closed":
            return
        # escalated / dead-man / failed-retries-exhausted → 链终点上升
        self._endpoint_escalate(
            item,
            reason=str(item.get("endpoint_reason") or "Arbiter 处置失败"),
            endpoint_kind=str(item.get("endpoint_kind") or "arbiter-escalated"),
            admin_trail=admin_trail,
        )

    # ── Admin 级（task 2.1/2.2/2.3）─────────────────────────────────

    def _run_admin_phase(self, item: dict, quota_cfg: dict) -> tuple:
        """链头 Admin 处置。返回 (admin_trail, phase)：

        - phase="closed"：处置成功，链闭环（side-effects 已落）；
        - phase="handoff"：超范围转单（不计失败），带尝试痕；
        - phase="exhausted"：尝试配额耗尽，转单 Arbiter，带尝试痕；
        - phase="deferred"：同 spec 在飞 admin run（互斥守卫），本件让行。
        """
        spec = str(item.get("spec") or "")
        sig = str(item.get("signature") or "")
        admin_quota = int(quota_cfg.get("admin_attempts") or 2)
        trail: List[dict] = []
        attempts = self._quota.admin_attempts(sig)
        while attempts < admin_quota:
            runner = self._resolve_runner()
            if runner is None:
                self._log("warning", "处置链 Admin 派发不可用（runner 缺席），转单 Arbiter")
                return trail, "exhausted"
            # 在飞互斥守卫复用（task 1.2）：同 spec 已有在飞 admin run 不双派
            if self._admin_run_in_flight(spec):
                return trail, "deferred"
            disp = self._dispatch_admin(item)
            record = {
                "run_id": disp.run_id,
                "result": disp.result,
                "success": bool(disp.success),
                "error": str(disp.error or "")[:400],
                "escalate": bool(disp.escalate),
            }
            handoff = str(getattr(disp, "handoff", "") or "").strip().lower()
            if handoff:
                record["handoff"] = handoff
                record["handoff_reason"] = str(
                    getattr(disp, "handoff_reason", "") or ""
                )[:400]
            trail.append(record)
            if handoff == "arbiter":
                # 超范围转单不计失败（task 2.1）——配额计数不变
                self._log(
                    "info",
                    f"Admin 超范围转单 Arbiter（不计失败）: sig={sig} "
                    f"reason={str(getattr(disp, 'handoff_reason', '') or '')[:120]}",
                )
                self._write_chain_event(
                    item,
                    kind="chain-handoff",
                    action_or_upgrade=(
                        f"Admin 超范围转单 Arbiter（handoff_reason="
                        f"{str(getattr(disp, 'handoff_reason', '') or '')[:200]}），"
                        f"Admin 尝试 {attempts}/{admin_quota} 不计失败"
                    ),
                    extra={"handoff_reason": str(getattr(disp, "handoff_reason", "") or "")},
                )
                item["admin_handoff_reason"] = str(
                    getattr(disp, "handoff_reason", "") or ""
                )
                return trail, "handoff"
            if disp.success and disp.result in ("resolved", "partially-resolved") and not disp.escalate:
                closed = self._close_chain_success(item, disp)
                self._log(
                    "info",
                    f"Admin 处置成功链闭环: sig={sig} run={disp.run_id} "
                    f"unfrozen={closed.get('unfrozen')}",
                )
                return trail, "closed"
            # 失败计一次（run 崩溃/超时/终态失败）
            attempts = self._quota.count_admin_attempt(sig)
            self._log(
                "warning",
                f"Admin 处置失败（{attempts}/{admin_quota}）: sig={sig} "
                f"run={disp.run_id} error={str(disp.error or '')[:160]}",
            )
        self._write_chain_event(
            item,
            kind="chain-handoff",
            action_or_upgrade=(
                f"Admin 尝试配额耗尽（{attempts}/{admin_quota}），转单 Arbiter"
                f"（附尝试痕 {len(trail)} 条 run 记录）"
            ),
        )
        return trail, "exhausted"

    def _admin_run_in_flight(self, spec: str) -> bool:
        """Admin 在飞互斥守卫（复用 admin_monitor 单源判定，fail-open False）。

        首参是 store 实例（admin_monitor 模块级单实现签名：``(store, spec,
        logger, ...)``）——链派发与 admin_monitor 巡检共用同一归并判定，
        不复制第二份在飞判定。
        """
        if not spec or spec == "global":
            return False
        try:
            from core.admin_monitor import _spec_has_active_admin_run
            from core.admin_store import AdminStore

            store = AdminStore(self.project_root, self.logger)
            return bool(_spec_has_active_admin_run(store, spec, self.logger))
        except Exception as e:
            self._log("warning", f"Admin 在飞互斥判定异常（按无在飞放行）: {e}")
            return False

    def _dispatch_admin(self, item: dict):
        """派发一次 Administrator 处置 run（同步；产物经 AdminDisposition）。"""
        from core.agent_runner.maintenance_runs import run_administrator

        runner = self._resolve_runner()
        from core.dashboard.data.adjudication_choices import choices_for_admin_chain

        admin_signal = {
            "signal_type": item.get("signal_type"),
            "spec": item.get("spec") or "global",
            "severity": item.get("severity") or "major",
            "description": item.get("description") or "",
            "evidence": item.get("evidence") or "",
            "recommended_action": item.get("recommended_action") or "",
            # 链上上下文（prompt_builder 注入消费）：链标识 + 环境运维拍板面
            # choices 子集（task 2.4——预算/豁免类不在 Admin 拍板面）
            "chain_id": item.get("chain_id") or "",
            "chain_level": "admin",
            "chain_choices": choices_for_admin_chain(str(item.get("signal_type") or "")),
        }
        return run_administrator(runner, admin_signal)

    def _close_chain_success(self, item: dict, disp) -> dict:
        """链内一级处置成功的闭环 side-effects（task 2.3）：

        - 显式 status 解冻（disp.status_after 合法且 spec 冻结时；
          拒绝 parse 兜底——缺显式 status 留冻结待人工，与 Arbiter 同型纪律）；
        - 收口在队上升件（task 4.1：链上任一级后续成功闭环时自动收口）；
        - 链事件台账留痕。
        """
        spec = str(item.get("spec") or "")
        side: Dict[str, Any] = {"unfrozen": False, "closed_escalations": 0}
        status_after = str(getattr(disp, "status_after", "") or "").strip()
        sm = self._resolve_state_machine()
        if sm is not None and spec and spec != "global":
            try:
                from core.state_machine import SpecStatus

                entry = (sm.read_all() or {}).get(spec) or {}
                if entry.get("frozen"):
                    if status_after and status_after in SpecStatus.ALL:
                        side["unfrozen"] = bool(sm.unfreeze_spec(spec, status=status_after))
                        side["unfreeze_status"] = status_after if side["unfrozen"] else None
                    else:
                        side["unfreeze_error"] = (
                            "处置记录未给合法显式 status（拒绝 parse 兜底，留冻结待人工）"
                        )
                        self._log(
                            "warning",
                            f"Admin 处置成功但缺显式 status_after，留冻结待人工: {spec}",
                        )
            except Exception as e:
                side["unfreeze_error"] = f"解冻执行异常: {e}"
                self._log("error", f"Admin 处置解冻异常 spec={spec}: {e}")
        # 收口在队上升件（本签名此前升级到人工队列的件随链成功自动闭环）
        side["closed_escalations"] = self._close_escalations_for_signature(item)
        self._write_chain_event(
            item,
            kind="chain-closed",
            action_or_upgrade=(
                f"Admin 处置成功链闭环（run={disp.run_id}，result={disp.result}）"
                + (f"，解冻→{side['unfreeze_status']}" if side.get("unfrozen") else "")
                + (f"，收口上升件 {side['closed_escalations']} 条" if side["closed_escalations"] else "")
            ),
            extra={"status_after": status_after},
        )
        return side

    def _close_escalations_for_signature(self, item: dict) -> int:
        try:
            from core.admin_store import AdminStore

            store = AdminStore(self.project_root, self.logger)
            return store.close_escalations_by_chain(
                signature=str(item.get("signature") or ""),
                resolve_note="处置链闭环自动收口",
            )
        except Exception as e:
            self._log("warning", f"上升件链上收口失败（fail-open）: {e}")
            return 0

    # ── Arbiter 级（task 3.x：复用车道调查机器，链同步驱动）─────────

    def _run_arbiter_phase(self, item: dict, admin_trail: List[dict], quota_cfg: dict) -> str:
        """链第二级 Arbiter。返回终态：closed / 其余（上升）。

        失败双轨（task 3.4）：车道自判失败/run 崩溃沿既有死人开关骨架重试
        （连败达 max_consecutive_failures 转 dead-man），链在 failed 期间
        循环重派（bounded by 车道内部计数），终点（escalated/dead-man/
        重试耗尽）交回链终点上升。
        """
        from core.pm_engine.arbiter import get_lane

        lane = get_lane(self.project_root, self.logger)
        if lane is None:
            item["endpoint_reason"] = "Arbiter 车道不可用（未装配）"
            item["endpoint_kind"] = "arbiter-unavailable"
            return "escalated"
        trigger = dict(item)
        trigger["admin_trail"] = admin_trail
        trigger["admin_handoff_reason"] = str(item.get("admin_handoff_reason") or "")
        trigger["source"] = f"chain-handoff:{item.get('source') or ''}"
        max_fail = int(
            lane.config().get("max_consecutive_failures") or 2
        )
        outcome = "failed"
        for _ in range(max(1, max_fail)):
            try:
                outcome = lane.process_chain_handoff(trigger)
            except Exception as e:
                self._log("error", f"Arbiter 级处理异常: {e}")
                outcome = "failed"
            if outcome != "failed":
                break
        if outcome == "resolved":
            # Arbiter 拍板成功：闭环 + 收口上升件
            side_unfrozen = bool(trigger.get("_chain_unfrozen"))
            closed = self._close_escalations_for_signature(item)
            self._write_chain_event(
                item,
                kind="chain-closed",
                action_or_upgrade=(
                    f"Arbiter 拍板成功链闭环（run={trigger.get('_chain_run_id')}）"
                    + (f"，收口上升件 {closed} 条" if closed else "")
                ),
            )
            self._log("info", f"Arbiter 拍板链闭环: sig={item.get('signature')}")
            return "closed"
        item["endpoint_reason"] = str(trigger.get("_chain_endpoint_reason") or "Arbiter 处置失败")
        item["endpoint_kind"] = str(
            trigger.get("_chain_endpoint_kind")
            or ("arbiter-dead-man" if outcome == "dead-man" else "arbiter-escalated")
        )
        item["arbiter_ledger_ids"] = list(trigger.get("_chain_ledger_ids") or [])
        item["arbiter_run_id"] = str(trigger.get("_chain_run_id") or "")
        return outcome

    # ── 链终点上升件（task 1.3：唯一人工落盘路径）───────────────────

    def _endpoint_escalate(
        self,
        item: dict,
        *,
        reason: str,
        endpoint_kind: str,
        admin_trail: Optional[List[dict]] = None,
    ):
        """链终点：经 family 咽喉写入上升件（附全链痕迹，防自环不再入链）。"""
        pm = self._resolve_pm()
        if pm is None:
            self._log(
                "error",
                f"链终点上升件落盘失败（pm 门面缺席）: sig={item.get('signature')} reason={reason}",
            )
            return
        chain_context = {
            "chain_id": item.get("chain_id") or "",
            "signature": item.get("signature") or "",
            "granularity": item.get("granularity") or "",
            "endpoint_kind": endpoint_kind,
            "endpoint_reason": reason[:500],
            "admin_attempts_used": self._quota.admin_attempts(
                str(item.get("signature") or "")
            ),
            "arbiter_rulings": self._quota.arbiter_rulings(
                str(item.get("signature") or "")
            ),
            "admin_trail": list(admin_trail or []),
            "handoff_reason": str(item.get("admin_handoff_reason") or "")[:400],
            "arbiter_run_id": str(item.get("arbiter_run_id") or ""),
            "arbiter_ledger_ids": list(item.get("arbiter_ledger_ids") or []),
        }
        try:
            pm._send_human_escalation_alert(
                str(item.get("spec") or ""),
                str(item.get("signal_type") or ""),
                str(item.get("severity") or "major"),
                str(item.get("description") or ""),
                str(item.get("evidence") or ""),
                str(item.get("recommended_action") or ""),
                trigger=item.get("trigger") or None,
                chain_context=chain_context,
            )
        except Exception as e:
            self._log("error", f"链终点上升件写入异常: {e}")
            return
        self._write_chain_event(
            item,
            kind="chain-escalated",
            action_or_upgrade=f"链终点上升人工（{endpoint_kind}）: {reason[:300]}",
            extra={"chain_id": chain_context["chain_id"]},
        )

    def _resolve_pm(self):
        """pm 门面回引（链终点上升件经 family 咽喉落盘；咽喉调用点惰性补）。"""
        return getattr(self, "_pm_ref", None)

    def set_pm(self, pm):
        self._pm_ref = pm

    # ── 判定助手 ────────────────────────────────────────────────────

    def _deadmanned(self, sig: str) -> bool:
        """dead-man 永久例外判定（台账 kind=dead-man 单源，跨重启有效）。"""
        try:
            from core.pm_engine.arbiter import load_arbiter_ledger

            for rec in load_arbiter_ledger(self.project_root):
                if (
                    str(rec.get("signature") or "") == sig
                    and rec.get("kind") in DEADMAN_LEDGER_KINDS
                ):
                    return True
        except Exception:
            pass
        return False

    def _write_chain_event(
        self, item: dict, *, kind: str, action_or_upgrade: str, extra: Optional[dict] = None
    ):
        """链事件落 arbiter 台账（时间轴/处置链视图联查单源；五段齐全）。"""
        try:
            from core.pm_engine.arbiter import arbiter_ledger_path

            entry = {
                "id": f"chain-ev-{int(time.time() * 1000)}",
                "created": _utcnow_iso(),
                "kind": kind,
                "spec": item.get("spec"),
                "signal_type": item.get("signal_type"),
                "signature": item.get("signature"),
                "chain_id": item.get("chain_id") or "",
                "run_id": item.get("arbiter_run_id") or "",
                # 五段结构（对齐 LEDGER_SEGMENT_KEYS；链事件以触发现场补位）
                "scene_snapshot": str(item.get("description") or "")[:4000]
                or f"链事件现场（source={item.get('source')}）",
                "forensic_timeline": [
                    {
                        "at": item.get("enqueued_at"),
                        "event": f"信号入链（source={item.get('source')}）",
                    },
                    {"at": _utcnow_iso(), "event": kind},
                ],
                "root_cause": (
                    f"granularity={item.get('granularity')}；"
                    f"signature={item.get('signature')}"
                ),
                "action_or_upgrade": action_or_upgrade[:4000],
                "evidence_refs": [str(item.get("evidence"))] if item.get("evidence") else [],
                "budget": {},
                "failure_reason": "",
            }
            if extra:
                entry.update(extra)
            path = arbiter_ledger_path(self.project_root)
            path.parent.mkdir(parents=True, exist_ok=True)
            from core.agent_runner.run_files import append_run_line

            append_run_line(path, entry)
        except Exception as e:
            self._log("warning", f"链事件台账写入失败（fail-open）: {e}")

    # ── 兜底看护消费点（admin_monitor 周期巡检调用）─────────────────

    def reap_stale_inflight(self) -> int:
        """清除超时在办登记（chain worker 死亡残留；返回清除条数）。

        看护语义（design 决策 1）：pending 超时升级由既有 admin_monitor
        孤儿接管路径承载（链派发的 admin run 沿用 pending disposition 落盘），
        本方法只回收状态文件内的登记残留并告警留痕。
        """
        stale = self._quota.stale_in_flight()
        if not stale:
            return 0

        def _drop(state):
            stale_ids = {str(x.get("chain_id") or "") for x in stale}
            state["in_flight"] = [
                x for x in state["in_flight"]
                if str(x.get("chain_id") or "") not in stale_ids
            ]

        self._quota._mutate(_drop)
        for item in stale:
            self._log(
                "warning",
                f"处置链在办件超时清除（chain_id={item.get('chain_id')} "
                f"phase={item.get('phase')} spec={item.get('spec')}）——"
                "底层 pending 处置记录走既有孤儿接管",
            )
        return len(stale)

    # ── 存量迁移（task 4.2）─────────────────────────────────────────

    def migrate_legacy_pending(self) -> dict:
        """存量 pending escalation 一次性迁移（版本哨兵防重跑）。

        能判定「底层已闭环」（同签名 spec 已终态）的旧 pending 告警自动收口
        （close_cause=migrated），其余保留人工队列；MUST NOT 回填入链。
        哨兵落链状态文件 meta 区（本模块 migration_done/mark_migration_done
        单源），迁移失败不落哨兵、下轮启动重试。
        """
        if migration_done(self.project_root):
            return {"status": "already-migrated"}
        try:
            from core.admin_store import AdminStore, ESCALATION

            sm = self._resolve_state_machine()
            specs = (sm.read_all() or {}) if sm is not None else {}
            terminal = {"done", "pushed", "abandoned"}
            store = AdminStore(self.project_root, self.logger)
            records = store.read_all()
            closed = 0
            kept = 0

            def _close(records_mut):
                nonlocal closed, kept
                changed = False
                for rec in records_mut:
                    if not isinstance(rec, dict) or rec.get("kind") != ESCALATION:
                        continue
                    if rec.get("handled"):
                        continue
                    if rec.get("chain"):
                        continue  # 链上升件不属存量迁移面
                    spec = str(rec.get("spec") or "")
                    entry = specs.get(spec) or {}
                    if str(entry.get("status") or "") in terminal:
                        rec["handled"] = True
                        rec["handled_at"] = _utcnow_iso()
                        rec["handled_by"] = "chain-migration"
                        rec["close_cause"] = "migrated"
                        rec["resolve_note"] = (
                            "存量迁移：底层 spec 已终态（"
                            f"{entry.get('status')}），旧 pending 告警自动收口"
                        )
                        closed += 1
                        changed = True
                    else:
                        kept += 1
                return changed

            store._mutate(_close, skip_unchanged=False)
            mark_migration_done(
                self.project_root, {"closed": closed, "kept": kept}
            )
            self._log(
                "info",
                f"存量迁移完成（版本哨兵 {CHAIN_MIGRATION_VERSION}）：收口 {closed} 条、"
                f"保留人工队列 {kept} 条，不回填入链",
            )
            return {"status": "ok", "closed": closed, "kept": kept}
        except Exception as e:
            self._log("warning", f"存量迁移执行失败（哨兵未落，下轮启动重试）: {e}")
            return {"status": "failed", "error": str(e)}

    # ── 只读快照（dashboard 处置链视图消费）─────────────────────────

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "queue_depth": self._queue.qsize(),
                "active_signatures": sorted(self._active),
                "in_flight": list(self._quota.stale_in_flight(0.0)),
            }


# ── 模块级单例与装配 ─────────────────────────────────────────────────────

_CHAIN: Optional[EscalationChain] = None
_CHAIN_LOCK = threading.Lock()


def get_chain(project_root=None, logger=None, pm=None) -> Optional[EscalationChain]:
    """取链单例（未装配时惰性建；project_root 缺失返回 None）。"""
    global _CHAIN
    if project_root is None:
        return _CHAIN
    with _CHAIN_LOCK:
        if _CHAIN is None or _CHAIN.project_root != Path(project_root):
            _CHAIN = EscalationChain(project_root, logger)
        elif logger is not None and _CHAIN.logger is None:
            _CHAIN.logger = logger
        if pm is not None and _CHAIN._resolve_pm() is None:
            _CHAIN.set_pm(pm)
        return _CHAIN


def set_chain(chain: Optional[EscalationChain]) -> None:
    """测试注入口：直接替换单例（None 清空）。"""
    global _CHAIN
    with _CHAIN_LOCK:
        _CHAIN = chain


def reset_chain() -> None:
    set_chain(None)
