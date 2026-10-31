"""core/pm_engine/arbiter.py — 全局决策者车道（add-arbiter-lane）。

把「框架外验尸者」制度化：冻结→人类的升级边改道为
冻结→Arbiter→（大多数）自主处置 /（少数）带裁决包升级。

设计真相源：docs/superpowers/specs/2026-10-31-arbiter-lane-design.md
（fbeb3f104，含用户四项裁定：mode=full 立即执行、纯提示词红线、裁决包
挂原告警静默更新、自主处置零用户可感知告警）。

模块职责：
- 触发面（双咽喉改道）：state_machine.freeze_for_human 咽喉（经
  ``install_freeze_hook`` 回调解耦注册）与 pm_engine._send_human_escalation_alert
  （直接调 :meth:`ArbiterLane.submit_for_alert`）。
- 存量回扫（add-arbiter-backlog-sweep）：事件驱动的触发面对已发生的存量
  冻结无效（事件在 Arbiter 存在前已流过咽喉）——:meth:`ArbiterLane.sweep_on_startup`
  （daemon 启动后一次）与 :meth:`ArbiterLane.observe_enabled_transition`
  （config 热更新 disabled→enabled 跃迁时一次）补存量回扫，命中者走
  同一 dedup/单飞/预算管线，不建第二套派发路径。
- 排除表：freeze_spec（人工冻结）/mark_frozen_hold（簿记）/frozen_until
  （定时自愈赛跑）在 state_machine 侧零接触（不挂钩即排除）；token 预算耗尽 /
  spec_integrity 内容缺失 / queue 异常类 signal 显式排除（本模块词表）。
- dedup：同 spec 同失败签名在飞只派发一次；处置成功后签名复发直接升级
  （design D6「处置后同根因复发」——失败不属复发，走死人开关连败计数）。
- 单飞：全局单飞队列串行——同一时刻至多一个 Arbiter run，后续触发排队；
  排队登记失败（队列满）MUST 显式报错，不吞 conflict 报假成功
  （scheduling_kick 单槽位「写侧吞 conflict 报假成功」前科规避）。
- 死人开关：同触发连败达 max_consecutive_failures（缺省 2）或单 run 超
  budget_wallclock_s/budget_tokens → 停止自主尝试、半成品调查包按挂靠
  语义升级，MUST NOT 静默死亡。
- 处置台账：五段结构（现场快照/取证时间轴/根因/处置动作或升级理由/证据
  回链）落 ``.fenix/arbiter_ledger.jsonl``。
- 告警零噪音分层：处置成功→原告警终态化 resolved_by=arbiter（不推送不进
  pending）；升级→同 alert_id 原位静默更新（报告进 narrative 槽位、choices/
  推荐注入原条目）并推 pending；两路径均不新增告警条目。
- 立项节流：同主题 drafted 在池不重复、单次调查至多 2 条、周配额 5
  （超配额只记台账）；立项一律 status 落 drafted。

权限边界（用户裁定）：提示词红线+台账审计，不做机械强制——见
agents/arbiter.md 置顶红线段；本模块不建白名单动作执行器、不建 per-run
deny hooks（现状所有 agent 本就以 bypassPermissions spawn）。
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
COMPONENT = "pm_engine.arbiter"

# ── 配置缺省（spec「配置与 Dashboard 设置页」四键）───────────────────────
ARBITER_ENABLED_DEFAULT = True
ARBITER_BUDGET_WALLCLOCK_S_DEFAULT = 1800
ARBITER_BUDGET_TOKENS_DEFAULT = 1_000_000
ARBITER_MAX_CONSECUTIVE_FAILURES_DEFAULT = 2

# 触发面排除表（design §9「不进」清单的 signal 维度）。freeze_spec /
# mark_frozen_hold / frozen_until 三路径在 state_machine 侧零接触（不挂钩
# 即排除）；本词表覆盖 _send_human_escalation_alert 直发信号的政策/数据完
# 整性类——留 narrative 与人类（与 design §7 白名单外清单一致）。
# 触发面正向白名单（spec「仅 blocked/frozen/争议类 condition 进触发面」）：
# 白名单取生产发射词汇（见下方常量定义处逐发射点注释）。judge_rerun_cap/
# verify_uniform_failure/verifier_infra_death/inconclusive_loop 等属
# stop-loss/自愈在先类，沿用既有 narrative 人工路径
# （tests/test_adjudication_narrative.py 在案契约）；
# 排除表（ARBITER_EXCLUDED_SIGNAL_TYPES）继续兜底政策/数据完整性类。
# 触发面白名单 = 生产发射词汇（2026-11-01 修正：曾锚历史回填词汇
# verify_fail_escalation——该名仅存在于 alert_lifecycle BACKFILL 分类器，
# 无任何生产发射点，白名单锚它即事件/回扫两路径整车道空转，evo-refine
# 存量回扫候选=0 实证）。四个信号名的发射点：
# - verify_env_blocked：freeze_for_human 冻结配对告警（escalation.py，
#   「验证环境阻塞」与「场景计划争议」两族同此名）
# - verdict_result_unreadable：pipeline 裁决缺失 fail-closed
# - blocked_stuck：admin_monitor blocked 超阈值未处理
# - manual-intervention：Administrator 处置请求（转人工边）
ARBITER_TRIGGER_SIGNAL_TYPES = frozenset(
    {
        "verify_env_blocked",
        "verdict_result_unreadable",
        "blocked_stuck",
        "manual-intervention",
    }
)
ARBITER_EXCLUDED_SIGNAL_TYPES = frozenset(
    {
        # token/实现预算政策类（预算政策属白名单外裁决，Arbiter 不拍板）
        "impl_budget_exhausted",
        "impl_budget_exempt_loop",
        # spec_integrity 内容缺失族（数据完整性，留 narrative 与人类）
        "spec_content_missing",
        "spec_delivered_no_content",
        # 派发队列基础设施异常（同因重派熔断——queue 异常类，留人类）
        "redispatch_loop_detected",
    }
)

# 车道命名（runner 车道表同源：run_files.RUN_ID_AGENT_PREFIXES "arbiter-" 行）
ARBITER_RUN_PREFIX = "arbiter-"
# 调查报告实例文件（run 按 prompt 写入、框架读回后清理，admin 处置族同范式）
ARBITER_REPORT_PREFIX = "arbiter_report-"
# 处置台账（append-only JSONL；.fenix 运行时目录不入库）
ARBITER_LEDGER_FILENAME = "arbiter_ledger.jsonl"

# model 钉（design D9：narrative 车道 10-09 前科——不钉则踩 [1M] 别名秒挂）。
# agents.models.arbiter 已分配时用分配值；未分配时钉死本值，MUST NOT 回落
# 默认网关官方模型名。
ARBITER_PINNED_MODEL = "glm-5.3-flash"

# 立项节流三限（design D7）
PROPOSAL_MAX_PER_RUN = 2
PROPOSAL_WEEKLY_QUOTA = 5

# 单飞队列深度上限：决策点是低频高价值动作，深度 8 已远超正常积压；
# 满队列 = 显式报错（排队登记失败 MUST NOT 吞 conflict 报假成功）。
ARBITER_QUEUE_MAX = 8

# 台账条目五段结构键（spec「调查报告与处置台账」）：缺任一段即不完整。
LEDGER_SEGMENT_KEYS = (
    "scene_snapshot",     # 现场快照
    "forensic_timeline",  # 取证时间轴
    "root_cause",         # 根因
    "action_or_upgrade",  # 处置动作或升级理由
    "evidence_refs",      # 证据回链
)


def arbiter_failure_signature(spec: str, signal_type: str) -> str:
    """失败签名（dedup 键单源）：``<spec>::<signal_type>``。

    同一冻结/升级事件经双咽喉（freeze_for_human → _send_human_escalation_alert）
    各报一次时，两处按 (spec, signal_type) 计算出同签名——第二咽喉自然命中
    dedup（绑 alert 而非重复派发），无需跨模块传递事件 id。
    """
    return f"{(spec or 'global').strip()}::{(signal_type or 'unknown').strip()}"


def arbiter_report_path(project_root, run_id: str) -> Path:
    """Arbiter 调查报告实例文件路径（.fenix/arbiter_report-<run_id>.json）。

    prompt 注入侧与框架读侧同源（admin_disposition_path 先例：注入值 =
    读侧路径，防双实现漂移）。
    """
    return Path(project_root) / ".fenix" / f"{ARBITER_REPORT_PREFIX}{run_id}.json"


def arbiter_ledger_path(project_root) -> Path:
    """处置台账路径（.fenix/arbiter_ledger.jsonl，append-only）。"""
    return Path(project_root) / ".fenix" / ARBITER_LEDGER_FILENAME


def load_arbiter_ledger(project_root) -> List[dict]:
    """读全量处置台账（最新在后）。损坏行跳过（fail-open，不阻断读侧）。"""
    path = arbiter_ledger_path(project_root)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return []
    out: List[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def ledger_entry_complete(entry: dict) -> bool:
    """台账条目五段完整性判定（spec「处置台账完整」验收口径）。"""
    if not isinstance(entry, dict):
        return False
    for key in LEDGER_SEGMENT_KEYS:
        val = entry.get(key)
        if val is None:
            return False
        if isinstance(val, str) and not val.strip():
            return False
        if isinstance(val, (list, tuple)) and not val:
            return False
    return True


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _week_start_iso(now: Optional[datetime] = None) -> str:
    """当前 ISO 周一 00:00 的 UTC ISO 串（周配额窗口锚点）。"""
    now = now or datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


class ArbiterLane:
    """全局决策者车道单例（每项目一个）：触发面 / dedup / 单飞 / 死人开关。

    生命周期：PMEngine 装配时 :func:`configure_lane` 注入 project_root 与
    logger；worker 线程懒启动（首个触发入队时拉起，daemon 线程不阻塞退出）。
    测试经 :func:`reset_lane` 清单例。
    """

    def __init__(self, project_root, logger=None):
        self.project_root = Path(project_root)
        self.logger = logger
        # RLock：submit 持锁内调 _bind_alert 会二次取锁（不可重入 Lock 死锁，
        # test_double_throat_single_dispatch_with_alert_bind 实测）——重入锁
        # 语义不变（同线程多次取放配平）。
        self._lock = threading.RLock()
        self._queue: "queue.Queue[dict]" = queue.Queue(maxsize=ARBITER_QUEUE_MAX)
        self._worker: Optional[threading.Thread] = None
        # dedup/复发记账：在飞+排队中的签名（防双咽喉重复派发）；已自主处置
        # 成功过的签名（同签名处置后复发 → 直接升级，design D6「处置后同根因
        # 复发」——注意失败≠处置后复发，失败走死人开关重试计数）；已死人开关
        # 停机的签名（后续同签名触发直接升级，不再自主尝试）。
        self._active: set = set()
        self._dispositioned: set = set()
        self._deadmanned: set = set()
        # 死人开关：签名 → 连续失败计数（成功清零；连败达阈值→停止自主尝试）
        self._failure_counts: Dict[str, int] = {}
        # 预算记账（贯穿 run 生命周期，验收「预算记账贯穿」）：run_id → 累计
        self._budget_ledger: Dict[str, dict] = {}
        # 在飞触发的迟到 alert 补绑表（签名 → alert_id；worker 取到触发时合并）
        self._pending_binds: Dict[str, str] = {}
        # 存量回扫（add-arbiter-backlog-sweep 1.1）跃迁记账：
        # _startup_swept——启动回扫每进程至多一次（重复调用幂等短路）；
        # _last_seen_enabled——热更新跃迁观察基线（None=未观测，False→True
        # 跃迁时回扫一次；True→False 不回扫，下次 False→True 再回扫一次）。
        self._startup_swept = False
        self._last_seen_enabled: Optional[bool] = None

    # ── 配置读取（热更新语义：每次触发/run 读取时即时解析）─────────────

    def config(self) -> dict:
        """读取 arbiter 四键（经 ConfigLoader 单源，脏值回退缺省）。"""
        try:
            from core.config import ConfigLoader

            raw = ConfigLoader.resolve_config(self.project_root)
            return ConfigLoader.get_arbiter_config(raw)
        except Exception as e:  # 配置链故障不阻断车道装配判定（fail-open 关）
            self._log("warning", f"arbiter 配置读取失败（按关闭态降级）: {e}")
            return {
                "enabled": False,
                "budget_wallclock_s": ARBITER_BUDGET_WALLCLOCK_S_DEFAULT,
                "budget_tokens": ARBITER_BUDGET_TOKENS_DEFAULT,
                "max_consecutive_failures": ARBITER_MAX_CONSECUTIVE_FAILURES_DEFAULT,
            }

    @property
    def enabled(self) -> bool:
        return bool(self.config().get("enabled"))

    @staticmethod
    def in_trigger_surface(signal_type: str) -> bool:
        """signal 维度触发面判定：正向白名单命中且不落排除表才进。

        白名单=blocked/frozen/争议类的生产发射词汇（ARBITER_TRIGGER_
        SIGNAL_TYPES 常量定义处有逐发射点注释）；排除表（token 预算/
        spec_integrity/queue 异常类）为第二道保险——白名单漏放政策类时
        排除表仍拦（spec MUST-NOT 清单零违反优先于多放行）。
        """
        sig = (signal_type or "").strip()
        return (
            sig in ARBITER_TRIGGER_SIGNAL_TYPES
            and sig not in ARBITER_EXCLUDED_SIGNAL_TYPES
        )

    def _log(self, level: str, message: str, context: Optional[dict] = None):
        log = getattr(self, "logger", None)
        if log is None:
            return
        try:
            getattr(log, level)(COMPONENT, message, context or None)
        except TypeError:
            # logger 不支持 context 第三参时降级两参形态
            getattr(log, level)(COMPONENT, message)
        except Exception:
            pass

    # ── 触发面入口（双咽喉共用）───────────────────────────────────────

    def submit_trigger(
        self,
        *,
        spec: str,
        signal_type: str,
        severity: str = "major",
        description: str = "",
        evidence: str = "",
        recommended_action: str = "",
        alert_id: Optional[str] = None,
        source: str = "",
    ) -> str:
        """登记一次升级边触发（``submit_trigger``——命名避开泛用 ``submit``，防 fidelity 扫描把本方法当全仓 ``submit`` 唯一 seam、误挂测试侧 Executor 替身）。返回处置字：

        - ``"disabled"``：arbiter.enabled=false（关闭态零侵扰——调用方应走
          既有 narrative/人工路径，本方法不做任何写入）；
        - ``"excluded"``：signal 在排除表（留 narrative 与人类）；
        - ``"deduped"``：同签名已派发/在飞——本次触发只绑 alert 不再派发；
        - ``"recurrence-escalated"``：同签名已派发过（复发）——按 design D6
          直接产裁决包升级，不再自主处置；
        - ``"queued"``：已入单飞队列（排队后串行消费）。

        排队登记失败（队列满）抛 RuntimeError——显式报错，MUST NOT 报假成功
        （scheduling_kick 单槽位前科规避，design §15）。
        """
        cfg = self.config()
        if not cfg.get("enabled"):
            return "disabled"
        if not self.in_trigger_surface(signal_type):
            return "excluded"
        sig = arbiter_failure_signature(spec, signal_type)
        with self._lock:
            if sig in self._active:
                # 同签名在飞/排队：只绑 alert（原位挂靠目标），不重复派发
                if alert_id:
                    self._bind_alert(sig, alert_id)
                self._log(
                    "info",
                    f"arbiter 触发 dedup（同签名在飞/排队）: sig={sig} alert={alert_id}",
                )
                return "deduped"
            if sig in self._deadmanned or sig in self._dispositioned:
                # 同签名复发/停机后复发：不再自主处置，直接产裁决包升级
                # （design D6）
                self._log(
                    "warning",
                    f"arbiter 同签名复发，跳过自主处置直接升级: sig={sig}",
                )
                self._record_recurrence_escalation(
                    spec=spec,
                    signal_type=signal_type,
                    sig=sig,
                    severity=severity,
                    description=description,
                    evidence=evidence,
                    alert_id=alert_id,
                )
                return "recurrence-escalated"
            trigger = {
                "spec": spec,
                "signal_type": signal_type,
                "severity": severity,
                "description": description,
                "evidence": evidence,
                "recommended_action": recommended_action,
                "alert_id": alert_id,
                "signature": sig,
                "source": source,
                "enqueued_at": _utcnow_iso(),
                "budget": {
                    "wallclock_s": cfg.get("budget_wallclock_s"),
                    "tokens": cfg.get("budget_tokens"),
                },
            }
            try:
                self._queue.put_nowait(trigger)
            except queue.Full:
                # 显式报错（不得吞 conflict 报假成功）：调用方按失败处理，
                # 告警走既有 narrative/人工路径
                raise RuntimeError(
                    f"arbiter 单飞队列已满（maxsize={ARBITER_QUEUE_MAX}），"
                    f"触发登记失败 spec={spec} signal={signal_type}"
                )
            self._active.add(sig)
        self._ensure_worker()
        self._log(
            "info",
            f"arbiter 触发入队（单飞串行）: sig={sig} alert={alert_id} source={source}",
        )
        return "queued"

    def submit_for_alert(self, pm, entry: dict, alert_id: str) -> str:
        """_send_human_escalation_alert 咽喉入口（alert 落地后调用）。

        告警已落盘（alert_id 可用），升级包/终态化均可原位挂靠。
        """
        return self.submit_trigger(
            spec=str(entry.get("spec") or "global"),
            signal_type=str(entry.get("signal_type") or ""),
            severity=str(entry.get("severity") or "major"),
            description=str(entry.get("description") or ""),
            evidence=str(entry.get("evidence") or ""),
            recommended_action=str(entry.get("recommended_action") or ""),
            alert_id=alert_id,
            source="escalation-alert",
        )

    # ── 存量回扫（add-arbiter-backlog-sweep 1.1）─────────────────────

    def sweep_on_startup(self) -> dict:
        """启动回扫入口：daemon 装配后调用一次（每进程至多一次）。

        ``arbiter.enabled=true`` 时执行一次存量回扫并把 enabled 基线落位
        （此后热更新跃迁观察以此为起点）；enabled=false 时只落基线零扫描
        零写入（关闭态零侵扰，s8 同口径）。重复调用幂等短路（不再扫描）。
        """
        with self._lock:
            if self._startup_swept:
                return {"status": "already-swept", "source": "startup"}
            self._startup_swept = True
        enabled = self.enabled
        with self._lock:
            self._last_seen_enabled = enabled
        if not enabled:
            self._log("info", "arbiter 启动回扫跳过（enabled=false，仅落跃迁基线）")
            return {"status": "disabled", "source": "startup"}
        return self.sweep_backlog(source="startup")

    def observe_enabled_transition(self) -> dict:
        """热更新跃迁观察：config disabled→enabled 跃迁时回扫一次。

        由 30s 配置热更新周期调用（fenixd._maybe_reload_config 接线）。观测
        当次 enabled 与上次基线：False→True 跃迁 → 执行一次存量回扫；
        True→False / 无跃迁 / 基线未落位（None→True，启动态由
        sweep_on_startup 负责）→ 不回扫。每条跃迁至多回扫一次（基线随即
        更新），派发层幂等另由同签名 dedup 兜底。
        """
        enabled = self.enabled
        with self._lock:
            prev = self._last_seen_enabled
            self._last_seen_enabled = enabled
        if prev is False and enabled:
            self._log("info", "arbiter 检测到 disabled→enabled 热更新跃迁，执行存量回扫")
            return self.sweep_backlog(source="hot-reload")
        return {
            "status": "no-transition",
            "source": "hot-reload",
            "previous": prev,
            "current": enabled,
        }

    def _pending_machine_alerts(self) -> Dict[str, dict]:
        """pending（未处理）机器升级告警索引：spec → 最新一条。

        机器升级告警 = kind=escalation ∧ 未 handled ∧ signal_type 在触发面
        白名单（ARBITER_TRIGGER_SIGNAL_TYPES，生产发射词汇——「冻结+告警」
        成对语义的告警半边）。
        freeze_spec 人工冻结不产告警对——无索引命中即天然排除（回扫判据
        反查侧）。read_all 最新在前，首个命中即该 spec 最新 pending 告警
        （同 spec 多条历史告警只取最新，回扫描述以最新现场为准）。
        """
        try:
            from core.admin_store import AdminStore, ESCALATION

            records = AdminStore(self.project_root, self.logger).read_all()
        except Exception as e:
            self._log("warning", f"arbiter 回扫告警索引读取失败（按空集降级）: {e}")
            return {}
        out: Dict[str, dict] = {}
        for rec in records:
            if not isinstance(rec, dict) or rec.get("kind") != ESCALATION:
                continue
            if rec.get("handled"):
                continue
            signal_type = str(rec.get("signal_type") or "")
            if not self.in_trigger_surface(signal_type):
                continue
            spec = str(rec.get("spec") or "")
            if spec and spec not in out:
                out[spec] = rec
        return out

    def _backlog_candidates(self, sm) -> List[dict]:
        """存量回扫候选判定：frozen=true ∧ 同 spec pending 机器升级告警。

        - ``frozen_until`` 非空（定时冻结）显式排除（scheduled-unfreeze 自愈
          在先，与事件触发面同口径）；
        - 无成对 pending 告警的 frozen 条目（人工冻结形态）排除；
        - 签名已在处置台账（任意 kind——disposition/escalation/failed/
          dead-man/recurrence 都代表 Arbiter 已调查过该签名）排除：跨重启
          幂等兜底（进程内存 dedup 集合随重启清空，台账是既有持久层，
          不另记回扫簿）；
        - spec 名路径不安全（内插 run_id/路径前科防御）排除。
        """
        try:
            specs = sm.read_all() or {}
        except Exception as e:
            self._log("warning", f"arbiter 回扫 STATE 读取失败（按空集降级）: {e}")
            return {}
        alert_index = self._pending_machine_alerts()
        ledger_sigs = {
            str(rec.get("signature") or "")
            for rec in load_arbiter_ledger(self.project_root)
        }
        out: List[dict] = []
        for name, entry in specs.items():
            e = entry or {}
            if not e.get("frozen"):
                continue
            if str(e.get("frozen_until") or "").strip():
                continue
            spec = str(name)
            alert = alert_index.get(spec)
            if alert is None:
                continue
            signal_type = str(alert.get("signal_type") or "")
            sig = arbiter_failure_signature(spec, signal_type)
            if sig in ledger_sigs:
                continue
            from core.pm_engine.verification.serving import _spec_name_path_error

            if _spec_name_path_error(spec):
                self._log(
                    "warning",
                    f"arbiter 回扫跳过路径不安全 spec={spec!r}",
                )
                continue
            out.append(
                {
                    "spec": spec,
                    "signal_type": signal_type,
                    "signature": sig,
                    "severity": str(alert.get("severity") or "major"),
                    "description": str(alert.get("description") or ""),
                    "evidence": str(alert.get("evidence") or ""),
                    "recommended_action": str(alert.get("recommended_action") or ""),
                    "alert_id": str(alert.get("id") or ""),
                }
            )
        return out

    def sweep_backlog(self, *, source: str = "backlog-sweep") -> dict:
        """执行一次存量回扫：命中者经既有 dedup/单飞/预算管线入队派发。

        判据见 :meth:`_backlog_candidates`。派发复用 :meth:`submit_trigger`
        （同签名 dedup / 单飞队列 / 预算随触发携带，不建第二套派发路径）；
        与事件触发竞写同签名时 submit_trigger 侧 dedup 兜底不重复派发。
        单个候选排队登记失败（队列满）不中断整轮回扫——其余候选继续，
        失败项显式记入返回摘要（不吞错报假成功）。
        """
        cfg = self.config()
        if not cfg.get("enabled"):
            self._log("info", f"arbiter 存量回扫跳过（enabled=false）source={source}")
            return {
                "status": "disabled",
                "source": source,
                "dispatched": [],
                "deduped": [],
                "skipped": [],
                "failed": [],
            }
        sm = self._resolve_state_machine()
        if sm is None:
            self._log("warning", "arbiter 存量回扫不可用（state_machine 未装配），跳过")
            return {
                "status": "unavailable",
                "source": source,
                "dispatched": [],
                "deduped": [],
                "skipped": [],
                "failed": [],
            }
        candidates = self._backlog_candidates(sm)
        dispatched: List[str] = []
        deduped: List[str] = []
        skipped: List[dict] = []
        failed: List[dict] = []
        for cand in candidates:
            sig = str(cand.get("signature") or "")
            try:
                outcome = self.submit_trigger(
                    spec=str(cand.get("spec") or "global"),
                    signal_type=str(cand.get("signal_type") or ""),
                    severity=str(cand.get("severity") or "major"),
                    description=str(cand.get("description") or ""),
                    evidence=str(cand.get("evidence") or ""),
                    recommended_action=str(cand.get("recommended_action") or ""),
                    alert_id=str(cand.get("alert_id") or "") or None,
                    source=source,
                )
            except RuntimeError as e:
                failed.append({"signature": sig, "error": str(e)[:300]})
                continue
            except Exception as e:  # 单候选故障不中断整轮（不吞：记摘要）
                failed.append({"signature": sig, "error": f"回扫派发异常: {e}"[:300]})
                continue
            if outcome == "queued":
                dispatched.append(sig)
            elif outcome == "deduped":
                deduped.append(sig)
            else:
                # disabled/excluded/recurrence-escalated：白名单判据下不应
                # 出现，显式记录供审计（不静默丢弃）
                skipped.append({"signature": sig, "outcome": outcome})
        summary = {
            "status": "ok",
            "source": source,
            "scanned": len(candidates),
            "dispatched": dispatched,
            "deduped": deduped,
            "skipped": skipped,
            "failed": failed,
        }
        self._log(
            "info",
            f"arbiter 存量回扫完成 source={source} 候选={len(candidates)} "
            f"派发={len(dispatched)} dedup={len(deduped)} 失败={len(failed)}",
        )
        return summary

    def _bind_alert(self, sig: str, alert_id: str):
        """把后落地的 alert_id 绑到已在飞/排队的同签名触发上。

        freeze_for_human 咽喉先入队（此刻 alert 尚未落盘）、告警写盘后
        _send_human_escalation_alert 咽喉再报同签名——本方法把 alert_id 补绑
        到触发上，处置成功/升级才有原位挂靠目标。绑定时签名在 set 中找不到
        对应 trigger（并发窗口）则静默跳过（dedup 语义不变）。
        """
        with self._lock:
            # queue 无检索原语：以快照重建方式补绑（队列深度上限 8，重建廉价）
            drained: List[dict] = []
            while True:
                try:
                    drained.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            bound = False
            for trig in drained:
                if not bound and trig.get("signature") == sig:
                    trig["alert_id"] = alert_id
                    bound = True
                try:
                    self._queue.put_nowait(trig)
                except queue.Full:  # pragma: no cover - 深度上限内自洽
                    self._log("error", f"arbiter 补绑回队失败（队列满）: sig={sig}")
            if bound:
                return
        # 队列中没有（可能已出队在飞）：登记到待绑表，worker 取到触发后合并
        # ——简化：在飞触发由 worker 消费时从 _pending_alert_binds 取补绑。
        with self._lock:
            self._pending_binds.setdefault(sig, alert_id)

    # ── worker（全局单飞串行消费）────────────────────────────────────

    def _ensure_worker(self):
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._worker_loop,
                daemon=True,
                name="arbiter-lane-worker",
            )
            self._worker.start()

    def _worker_loop(self):
        while True:
            try:
                trigger = self._queue.get()
            except Exception:  # pragma: no cover - 队列关闭等病态
                continue
            try:
                sig = trigger.get("signature") or ""
                with self._lock:
                    bind = self._pending_binds.pop(sig, None)
                    if bind and not trigger.get("alert_id"):
                        trigger["alert_id"] = bind
                self._process_trigger(trigger)
            except Exception as e:
                # 单个触发的处理崩溃不得杀死 worker（静默死亡反例：至少落日志）
                self._log("error", f"arbiter 触发处理异常（继续下一触发）: {e}")
            finally:
                try:
                    self._queue.task_done()
                except Exception:
                    pass

    # ── 主流程（4.1）：消费 → 调查 run → 分类 → 处置/升级 ─────────────

    def _process_trigger(self, trigger: dict):
        spec = str(trigger.get("spec") or "global")
        try:
            result = self._run_investigation(trigger)
        except Exception as e:
            result = {"ok": False, "error": f"arbiter run 派发异常: {e}", "report": {}}
        report = result.get("report") or {}
        budget = result.get("budget") or {}
        if not result.get("ok"):
            self._on_run_failed(trigger, result, budget)
            return
        outcome = str(report.get("outcome") or "").strip().lower()
        if outcome == "resolved":
            self._on_disposition_success(trigger, result, budget)
        elif outcome == "escalate":
            self._on_escalate(
                trigger,
                result,
                budget,
                reason=str(report.get("escalation_reason") or "arbiter 判定须人类拍板"),
            )
        else:
            # 产物硬门外的语义失败（outcome 非法/缺失）按失败计（死人开关）
            self._on_run_failed(
                trigger,
                {
                    "ok": False,
                    "error": f"arbiter 报告 outcome 非法: {outcome!r}",
                    "report": report,
                },
                budget,
            )

    def _run_investigation(self, trigger: dict) -> dict:
        """启动一次 dsh 车道调查 run（run_arbiter；预算记账贯穿 run 生命周期）。

        预算记账（验收「预算记账贯穿」）：墙钟由 _effective_run_timeout 对
        arbiter 取 min 封顶（2.1），token 事后记账（usage_info 四键累计）；
        两维耗尽位进 budget dict 供死人开关判定。
        """
        from core.agent_runner import maintenance_runs

        runner = self._resolve_runner()
        if runner is None:
            return {"ok": False, "error": "agent_runner 不可用（车道未装配）", "report": {}}
        result = maintenance_runs.run_arbiter(runner, trigger)
        usage = result.get("usage_info") or {}
        tokens_used = sum(
            int(usage.get(k) or 0)
            for k in (
                "input_tokens",
                "output_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            )
        )
        cfg = self.config()
        token_budget = int(cfg.get("budget_tokens") or ARBITER_BUDGET_TOKENS_DEFAULT)
        wall_budget = float(
            cfg.get("budget_wallclock_s") or ARBITER_BUDGET_WALLCLOCK_S_DEFAULT
        )
        elapsed = float(result.get("elapsed_s") or 0.0)
        result["budget"] = {
            "started_at": trigger.get("enqueued_at"),
            "finished_at": _utcnow_iso(),
            "wallclock_budget_s": wall_budget,
            "elapsed_s": elapsed,
            "wallclock_exhausted": bool(wall_budget > 0 and elapsed > wall_budget),
            "tokens_used": tokens_used,
            "token_budget": token_budget,
            "tokens_exhausted": bool(token_budget > 0 and tokens_used > token_budget),
        }
        return result

    def _resolve_runner(self):
        """取 AgentRunner 门面（PMEngine 装配时注入；测试可直设）。"""
        runner = getattr(self, "_runner_ref", None)
        return runner

    def set_runner(self, runner):
        self._runner_ref = runner

    # ── 结果分类三出口 ────────────────────────────────────────────────

    def _on_disposition_success(self, trigger: dict, result: dict, budget: dict):
        """处置成功：框架侧直执行收尾 + 告警零噪音终态化 + 台账五段 + 清零。"""
        sig = str(trigger.get("signature") or "")
        with self._lock:
            self._failure_counts.pop(sig, None)
            self._active.discard(sig)
            self._dispositioned.add(sig)
        report = result.get("report") or {}
        side = self._apply_disposition_side_effects(trigger, report)
        alert_id = trigger.get("alert_id")
        evidence_ref = "; ".join(str(x) for x in (report.get("evidence_refs") or []))
        action_text = self._render_actions(report)
        if side.get("unfrozen"):
            action_text += f"；解冻→显式 status={side.get('unfreeze_status')}"
        elif side.get("unfreeze_error"):
            action_text += f"；解冻未执行（{side['unfreeze_error']}）"
        if side.get("cleaned_paths"):
            action_text += f"；清理无主产物 {len(side['cleaned_paths'])} 项"
        entry = self._write_ledger(
            trigger,
            result,
            kind="disposition",
            report=report,
            budget=budget,
            action_or_upgrade=action_text,
            status_after=str(report.get("status_after") or side.get("unfreeze_status") or ""),
        )
        resolved = False
        if alert_id:
            resolved = self._finalize_alert(
                alert_id,
                summary=str(report.get("summary") or ""),
                evidence_ref=evidence_ref or str(entry.get("ledger_id") or ""),
                run_id=str(result.get("run_id") or ""),
            )
        self._log(
            "info",
            f"arbiter 自主处置完成 spec={trigger.get('spec')} sig={sig} "
            f"alert_finalized={resolved} ledger={entry.get('ledger_id')} side={side}",
        )
        self._apply_proposals(trigger, report)

    def _apply_disposition_side_effects(self, trigger: dict, report: dict) -> dict:
        """处置动作框架侧直执行（4.1 ①③类收尾；解冻含验证计数清零语义）。

        - 解冻：报告 status_after 是合法 SpecStatus 且 spec 当前 frozen 时执行
          ``unfreeze_spec(spec, status=<显式值>)``——绝不依赖 parse_orig_status
          ready 兜底（spec「显式 status 解冻」硬约束）；报告缺显式 status 时
          解冻不执行、留冻结待人工（宁可不动状态也不拍脑袋解冻）。
          unfreeze_spec 自带「重启重验计数一并清零」（fix-daemon-lifecycle-races
          D3）——③验证计数清零由该调用一并完成，不另设清零写点。
        - 清理（②删除无主坏产物）：报告 cleanup_paths 经 ``_safe_cleanup_path``
          白名单过滤后删除（越界/敏感路径一律拒绝）。
        """
        spec = str(trigger.get("spec") or "")
        side: Dict[str, Any] = {"unfrozen": False, "cleaned_paths": []}
        status_after = str(report.get("status_after") or "").strip()
        sm = self._resolve_state_machine()
        if sm is not None and spec and spec != "global":
            try:
                from core.state_machine import SpecStatus

                entry = (sm.read_all() or {}).get(spec) or {}
                # 冻结判定（fix-restart-dual-dispatch S4 结构化字段口径）：
                # frozen=True 字段而非 "frozen" 状态值——机器冻结落
                # status=blocked + frozen=True（freeze_for_human 单一入口）
                if entry.get("frozen"):
                    if status_after and status_after in SpecStatus.ALL:
                        side["unfrozen"] = bool(
                            sm.unfreeze_spec(spec, status=status_after)
                        )
                        side["unfreeze_status"] = (
                            status_after if side["unfrozen"] else None
                        )
                    else:
                        side["unfreeze_error"] = (
                            "报告未给合法显式 status（拒绝 parse 兜底，留冻结待人工）"
                        )
            except Exception as e:
                side["unfreeze_error"] = f"解冻执行异常: {e}"
                self._log("error", f"arbiter 解冻执行异常 spec={spec}: {e}")
        for raw in (report.get("cleanup_paths") or []):
            path = self._safe_cleanup_path(raw)
            if path is None:
                continue
            try:
                if path.is_dir():
                    import shutil

                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
                side["cleaned_paths"].append(str(path))
            except OSError as e:
                self._log("warning", f"arbiter 无主产物清理失败 path={path}: {e}")
        return side

    def _safe_cleanup_path(self, raw) -> Optional[Path]:
        """cleanup_paths 白名单过滤（②类动作的有界执行边界）。

        只放行两类「无主坏产物」位置：``.claude/worktrees/<name>``（孤儿
        worktree）与 ``.fenix/tmp/**``；其余一律拒绝（防报告注入把清理变成
        任意删——spec「白名单外只产裁决包不擅动」的框架侧镜像）。
        """
        try:
            root = self.project_root.resolve()
            path = Path(str(raw or "")).expanduser()
            if not path.is_absolute():
                path = root / path
            path = path.resolve()
        except (OSError, ValueError):
            return None
        if path == root or root not in path.parents:
            return None
        try:
            rel = path.relative_to(root)
        except ValueError:
            return None
        parts = rel.parts
        if len(parts) >= 2 and parts[0] == ".claude" and parts[1] == "worktrees":
            return path
        if len(parts) >= 2 and parts[0] == ".fenix" and parts[1] == "tmp":
            return path
        return None

    def _on_escalate(self, trigger: dict, result: dict, budget: dict, reason: str):
        """升级：裁决包同 alert_id 原位静默更新 + 推 pending + 台账。"""
        sig = str(trigger.get("signature") or "")
        with self._lock:
            self._active.discard(sig)
        report = result.get("report") or {}
        self._write_ledger(
            trigger,
            result,
            kind="escalation",
            report=report,
            budget=budget,
            action_or_upgrade=reason,
            status_after="",
        )
        alert_id = trigger.get("alert_id")
        if alert_id:
            self._upgrade_alert(
                alert_id,
                report=report,
                recommended=str(
                    report.get("recommended_action")
                    or trigger.get("recommended_action")
                    or ""
                ),
                run_id=str(result.get("run_id") or ""),
                reason=reason,
            )
        self._log(
            "warning",
            f"arbiter 产裁决包升级 spec={trigger.get('spec')} sig={sig} reason={reason[:120]}",
        )
        self._apply_proposals(trigger, report)

    def _on_run_failed(self, trigger: dict, result: dict, budget: dict):
        """失败路径：连败计数 → 死人开关（半成品包升级）/ 留待下次触发重试。"""
        sig = str(trigger.get("signature") or "")
        cfg = self.config()
        max_fail = int(
            cfg.get("max_consecutive_failures")
            or ARBITER_MAX_CONSECUTIVE_FAILURES_DEFAULT
        )
        with self._lock:
            count = self._failure_counts.get(sig, 0) + 1
            self._failure_counts[sig] = count
            self._active.discard(sig)
        reason = str(result.get("error") or "run 失败")
        half_report = {
            "summary": str((result.get("report") or {}).get("summary") or ""),
            "evidence_refs": (result.get("report") or {}).get("evidence_refs") or [],
        }
        if count >= max_fail or budget.get("tokens_exhausted") or budget.get(
            "wallclock_exhausted"
        ):
            with self._lock:
                self._deadmanned.add(sig)
            switch = (
                f"连败 {count}/{max_fail}"
                if count >= max_fail
                else "预算耗尽"
            )
            self._write_ledger(
                trigger,
                result,
                kind="dead-man",
                report={
                    "summary": half_report["summary"],
                    "evidence_refs": half_report["evidence_refs"],
                },
                budget=budget,
                action_or_upgrade=f"死人开关触发（{switch}）：停止自主尝试，半成品调查包升级人类。失败原因: {reason}",
                status_after="",
            )
            alert_id = trigger.get("alert_id")
            if alert_id:
                self._upgrade_alert(
                    alert_id,
                    report={
                        "summary": half_report["summary"]
                        or f"Arbiter run 未产出完整调查报告（{switch}）",
                        "evidence_refs": half_report["evidence_refs"],
                    },
                    recommended=str(trigger.get("recommended_action") or ""),
                    run_id=str(result.get("run_id") or ""),
                    reason=f"死人开关（{switch}）: {reason}",
                )
            self._log(
                "error",
                f"arbiter 死人开关触发 spec={trigger.get('spec')} sig={sig} "
                f"({switch})，半成品包升级 alert={alert_id}",
            )
        else:
            self._write_ledger(
                trigger,
                result,
                kind="failed",
                report=half_report,
                budget=budget,
                action_or_upgrade=f"run 失败（{count}/{max_fail}），等待同签名下次触发重试: {reason}",
                status_after="",
            )
            self._log(
                "warning",
                f"arbiter run 失败 spec={trigger.get('spec')} sig={sig} "
                f"({count}/{max_fail}): {reason[:160]}",
            )

    # ── 处置台账（4.2）───────────────────────────────────────────────

    def _write_ledger(
        self,
        trigger: dict,
        result: dict,
        *,
        kind: str,
        report: dict,
        budget: dict,
        action_or_upgrade: str,
        status_after: str,
    ) -> dict:
        """追加一条五段台账（现场快照/取证时间轴/根因/处置动作或升级理由/证据回链）。"""
        # 五段结构（LEDGER_SEGMENT_KEYS 同序）各段缺省补全（s7 台账完整验收）：
        # 失败/死人开关路径报告缺段时以真实失败现场/run 归档回链补位——落
        # 「无现场快照」式空占位等于缺段。
        failure_reason = str(result.get("error") or "")
        run_id_eff = result.get("run_id") or trigger.get("run_id")
        scene = str(report.get("scene_snapshot") or trigger.get("description") or "")
        if not scene.strip():
            scene = (
                f"run 失败现场（kind={kind}）: {failure_reason[:600]}"
                if failure_reason
                else f"触发现场（source={trigger.get('source')}，报告未带快照）"
            )
        root = str(report.get("root_cause") or "")
        if not root.strip():
            root = (
                "run 未产出根因（失败终点，成因见 action_or_upgrade 与失败现场）"
                if kind in ("failed", "dead-man")
                else ""
            )
        evidence = list(report.get("evidence_refs") or [])
        if not evidence and run_id_eff:
            # 真实回链：run 归档转录（调查过程事实所在）
            evidence = [f".fenix/runs/{run_id_eff}.jsonl"]
        entry = {
            "id": f"arb-ledger-{int(time.time() * 1000)}",
            "created": _utcnow_iso(),
            "kind": kind,
            "spec": trigger.get("spec"),
            "signal_type": trigger.get("signal_type"),
            "signature": trigger.get("signature"),
            "alert_id": trigger.get("alert_id"),
            "run_id": run_id_eff,
            # 五段结构（LEDGER_SEGMENT_KEYS 同序）
            "scene_snapshot": scene[:4000],
            "forensic_timeline": report.get("forensic_timeline")
            or [
                {
                    "at": trigger.get("enqueued_at"),
                    "event": f"触发入队（source={trigger.get('source')}）",
                },
                {
                    "at": budget.get("started_at"),
                    "event": f"调查 run 启动 run_id={run_id_eff}",
                },
                {"at": budget.get("finished_at"), "event": f"run 终态 kind={kind}"},
            ],
            "root_cause": root[:4000],
            "action_or_upgrade": action_or_upgrade[:4000],
            "evidence_refs": evidence,
            "status_before": str(report.get("status_before") or trigger.get("status_before") or ""),
            "status_after": status_after,
            "budget": dict(budget or {}),
            "failure_reason": failure_reason,
        }
        path = arbiter_ledger_path(self.project_root)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(entry, ensure_ascii=False)
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            self._log("error", f"arbiter 台账写入失败（kind={kind}）: {e}")
        return entry

    # ── 告警零噪音分层（4.3）─────────────────────────────────────────

    def _finalize_alert(self, alert_id: str, *, summary: str, evidence_ref: str, run_id: str) -> bool:
        """处置成功：原告警终态化 resolved_by=arbiter（不推送不进 pending）。"""
        try:
            from core.admin_store import AdminStore

            store = AdminStore(self.project_root, self.logger)
            return store.arbiter_resolve(
                alert_id,
                summary=summary,
                evidence_ref=evidence_ref,
                run_id=run_id,
            )
        except Exception as e:
            self._log("error", f"arbiter 告警终态化失败 alert={alert_id}: {e}")
            return False

    def _upgrade_alert(
        self,
        alert_id: str,
        *,
        report: dict,
        recommended: str,
        run_id: str,
        reason: str,
    ) -> bool:
        """升级：裁决包同 alert_id 原位静默更新 + 推 pending（不新增条目）。

        报告进 narrative 槽位（sidecar，model=arbiter）；choices/推荐注入
        原条目；handled 翻回 False 使条目进入 pending 人工队列。
        """
        try:
            from core.adjudication_narrative import write_narrative_sidecar

            report_text = self._render_upgrade_report(report, reason, run_id)
            write_narrative_sidecar(self.project_root, alert_id, report_text, "arbiter")
        except Exception as e:
            self._log("error", f"arbiter 裁决包 narrative 槽位写入失败 alert={alert_id}: {e}")
        try:
            from core.admin_store import AdminStore

            store = AdminStore(self.project_root, self.logger)
            return store.arbiter_upgrade(
                alert_id,
                summary=str(report.get("summary") or ""),
                recommended_action=recommended,
                run_id=run_id,
                reason=reason,
            )
        except Exception as e:
            self._log("error", f"arbiter 告警原位升级失败 alert={alert_id}: {e}")
            return False

    @staticmethod
    def _render_actions(report: dict) -> str:
        actions = report.get("actions_taken") or []
        if isinstance(actions, str):
            return actions
        return "; ".join(str(a) for a in actions)

    def _render_upgrade_report(self, report: dict, reason: str, run_id: str) -> str:
        """裁决包（报告+选项+推荐）渲染为 narrative 槽位文本。"""
        lines = [
            "## Arbiter 调查报告（裁决包）",
            f"- run: {run_id or 'unknown'}",
            f"- 升级理由: {reason}",
            "",
            "### 调查结论",
            str(report.get("summary") or "（无摘要）"),
            "",
            "### 根因",
            str(report.get("root_cause") or "（未定位）"),
            "",
            "### 处置选项与推荐",
            str(report.get("recommended_action") or "（无推荐——请人工现场裁决）"),
        ]
        refs = report.get("evidence_refs") or []
        if refs:
            lines.append("")
            lines.append("### 证据回链")
            for ref in refs:
                lines.append(f"- {ref}")
        return "\n".join(lines)

    # ── 复发升级（design D6：同签名只自主处置一次）────────────────────

    def _record_recurrence_escalation(
        self,
        *,
        spec: str,
        signal_type: str,
        sig: str,
        severity: str,
        description: str,
        evidence: str,
        alert_id: Optional[str],
    ) -> None:
        """同签名复发：不经 run 直接产裁决包挂新告警升级。"""
        trigger = {
            "spec": spec,
            "signal_type": signal_type,
            "signature": sig,
            "severity": severity,
            "description": description,
            "alert_id": alert_id,
            "source": "recurrence",
            "enqueued_at": _utcnow_iso(),
        }
        self._write_ledger(
            trigger,
            {"run_id": None, "error": ""},
            kind="recurrence-escalation",
            report={
                "summary": f"同签名 {sig} 此前已自主处置过一次，处置后复发——按 design D6 不再自主处置。",
                "evidence_refs": [evidence] if evidence else [],
            },
            budget={},
            action_or_upgrade=(
                "同签名复发直接升级（同 spec 同失败签名只自主处置一次，"
                "10-31 第 2 轮同根因复发教训）"
            ),
            status_after="",
        )
        if alert_id:
            self._upgrade_alert(
                alert_id,
                report={
                    "summary": (
                        f"同签名复发（{sig}）：Arbiter 此前已自主处置过一次，"
                        "按「同签名只自主处置一次」纪律本次不再处置，直接升级人工。"
                    ),
                    "root_cause": str(description or "")[:2000],
                    "evidence_refs": [evidence] if evidence else [],
                },
                recommended=str(description or ""),
                run_id="",
                reason="同签名复发（design D6）",
            )

    # ── 立项节流写点（4.4）───────────────────────────────────────────

    def _apply_proposals(self, trigger: dict, report: dict):
        """消费调查报告的立项提案（三限节流；立项一律 status 落 drafted）。

        同主题 drafted 在池（主题/capability 级匹配）不重复立项；单次至多
        PROPOSAL_MAX_PER_RUN 条；ISO 周配额 PROPOSAL_WEEKLY_QUOTA 条，超配额
        只记台账不落池。
        """
        proposals = report.get("proposals") or []
        if not isinstance(proposals, list) or not proposals:
            return
        sm = self._resolve_state_machine()
        if sm is None:
            self._log("warning", "arbiter 立项写点不可用（state_machine 未装配），提案只记台账")
            return
        drafted_names, drafted_blob = self._drafted_pool(sm)
        week_anchor = _week_start_iso()
        weekly_used = sum(
            1
            for rec in load_arbiter_ledger(self.project_root)
            if rec.get("kind") == "spec-proposed" and str(rec.get("created") or "") >= week_anchor
        )
        accepted = 0
        for prop in proposals:  # 全量遍历：超限提案逐条记台账（不静默丢弃）
            topic = str((prop or {}).get("topic") or "").strip()
            name = str((prop or {}).get("spec_name") or "").strip()
            rationale = str((prop or {}).get("rationale") or "").strip()
            if not topic:
                continue
            hit = self._topic_in_pool(topic, drafted_names, drafted_blob)
            if hit:
                self._write_ledger(
                    trigger, {"run_id": trigger.get("run_id"), "error": ""},
                    kind="proposal-dedup",
                    report={"summary": f"提案主题「{topic}」与 drafted 在池 SPEC「{hit}」同主题，不重复立项。",
                            "evidence_refs": [".fenix/STATE.md"]},
                    budget={},
                    action_or_upgrade=f"同主题 drafted 在池不立项（关联指向 {hit}）",
                    status_after="",
                )
                continue
            if accepted >= PROPOSAL_MAX_PER_RUN:
                self._throttle_ledger(trigger, topic, "单次调查至多 2 条")
                continue
            if weekly_used >= PROPOSAL_WEEKLY_QUOTA:
                self._throttle_ledger(trigger, topic, f"周配额 {PROPOSAL_WEEKLY_QUOTA} 已满")
                continue
            spec_name = name or self._proposal_spec_name(topic)
            entry = {
                "status": "drafted",
                "priority": 5,
                "error": f"arbiter 立项: {rationale}"[:500],
            }
            ok = False
            try:
                ok = sm.add_spec(spec_name, entry)
            except Exception as e:
                self._log("error", f"arbiter 立项写入失败 spec={spec_name}: {e}")
            accepted += 1 if ok else 0
            if ok:
                weekly_used += 1
                self._write_ledger(
                    trigger, {"run_id": trigger.get("run_id"), "error": ""},
                    kind="spec-proposed",
                    report={"summary": f"立项 {spec_name}（topic={topic}）status=drafted，走既有 evo ready 人审门。",
                            "evidence_refs": [".fenix/STATE.md"]},
                    budget={},
                    action_or_upgrade=f"立项落 drafted: {spec_name}",
                    status_after="drafted",
                )
            else:
                self._write_ledger(
                    trigger, {"run_id": trigger.get("run_id"), "error": ""},
                    kind="proposal-dedup",
                    report={"summary": f"提案 {spec_name} 已在池（add_spec 查重拒绝）。",
                            "evidence_refs": [".fenix/STATE.md"]},
                    budget={},
                    action_or_upgrade="同主题 drafted 在池不立项（add_spec 存在性查重命中）",
                    status_after="",
                )

    def _resolve_state_machine(self):
        sm = getattr(self, "_state_machine_ref", None)
        return sm

    def set_state_machine(self, sm):
        self._state_machine_ref = sm

    def _drafted_pool(self, sm) -> tuple:
        """读 drafted/reviewing 在池 SPEC 名集与全名拼接串（主题级匹配用）。"""
        names: List[str] = []
        try:
            specs = sm.read_all() or {}
            for name, entry in specs.items():
                if str((entry or {}).get("status") or "") in ("drafted", "reviewing"):
                    names.append(str(name))
        except Exception as e:
            self._log("warning", f"arbiter drafted 池读取失败（按空池降级）: {e}")
        return set(names), " ".join(names).lower()

    @staticmethod
    def _topic_in_pool(topic: str, drafted_names: set, drafted_blob: str) -> str:
        """主题/capability 级匹配：主题词（去空白切分，长度≥2）任一命中在池
        SPEC 名即视为同主题。保守匹配（宁 dedup 不重复立项）。"""
        tokens = [t for t in topic.replace("-", " ").replace("_", " ").split() if len(t) >= 2]
        blob = drafted_blob.lower()
        for token in tokens:
            if token.lower() in blob:
                for name in sorted(drafted_names):
                    if token.lower() in name.lower():
                        return name
        return ""

    @staticmethod
    def _proposal_spec_name(topic: str) -> str:
        """由主题合成 spec 名（小写连字符、截 48 字符，非法字符折叠为 -）。"""
        cleaned = []
        for ch in topic.lower():
            if ch.isalnum() or ch == "-":
                cleaned.append(ch)
            else:
                # 空白/下划线/路径分隔/非 ASCII 一律折叠为 -（非 ASCII 主题
                # 经折叠仍保留 token 结构，可读且不撞 spec 名路径校验）
                cleaned.append("-")
        name = "".join(cleaned)
        while "--" in name:
            name = name.replace("--", "-")
        return f"arb-{name.strip('-')[:48] or 'gap'}"

    def _throttle_ledger(self, trigger: dict, topic: str, reason: str):
        self._write_ledger(
            trigger, {"run_id": trigger.get("run_id"), "error": ""},
            kind="proposal-throttled",
            report={"summary": f"提案「{topic}」超立项节流（{reason}），只记台账不落池。",
                    "evidence_refs": []},
            budget={},
            action_or_upgrade=f"立项节流（{reason}）",
            status_after="",
        )


# ── 模块级单例与装配 ─────────────────────────────────────────────────────

_LANE: Optional[ArbiterLane] = None
_LANE_LOCK = threading.Lock()


def get_lane(project_root=None, logger=None) -> Optional[ArbiterLane]:
    """取车道单例（未装配时惰性建：project_root 缺失返回 None）。"""
    global _LANE
    if project_root is None:
        return _LANE
    with _LANE_LOCK:
        if _LANE is None or _LANE.project_root != Path(project_root):
            _LANE = ArbiterLane(project_root, logger)
        elif logger is not None and _LANE.logger is None:
            _LANE.logger = logger
        return _LANE


def set_lane(lane: Optional[ArbiterLane]) -> None:
    """测试注入口：直接替换单例（None 清空）。"""
    global _LANE
    with _LANE_LOCK:
        _LANE = lane


def reset_lane() -> None:
    set_lane(None)


# ── state_machine 咽喉回调解耦（1.1 的注册端）────────────────────────────

def install_freeze_hook() -> None:
    """把 freeze_for_human 咽喉的 Arbiter 派发回调注册进 state_machine。

    幂等（重复安装零副作用）；回调解耦——state_machine 不 import 本模块，
    只持有可调用。enabled=false 时回调内部短路（submit 返回 disabled，
    零写入），升级边行为与现状逐字节一致（s8）。
    """
    from core import state_machine as _sm

    def _on_machine_freeze(**kwargs):
        lane = get_lane()
        if lane is None:
            return
        try:
            lane.submit_trigger(
                spec=str(kwargs.get("spec_name") or "global"),
                signal_type=str(kwargs.get("signal_type") or ""),
                severity=str(kwargs.get("severity") or "major"),
                description=str(kwargs.get("description") or ""),
                evidence=str(kwargs.get("evidence") or ""),
                recommended_action=str(kwargs.get("recommended_action") or ""),
                alert_id=None,  # 冻结先于告警落盘：alert 后由告警咽喉补绑
                source="freeze_for_human",
            )
        except RuntimeError as e:
            # 排队登记失败显式留痕（吞掉会变成「看起来注册了其实没排上」）
            if lane.logger is not None:
                lane.logger.warning(COMPONENT, f"arbiter 冻结触发登记失败: {e}")
        except Exception as e:  # 触发面故障不回滚冻结本身（与告警容错同口径）
            if lane.logger is not None:
                lane.logger.warning(COMPONENT, f"arbiter 冻结触发异常（非阻塞）: {e}")

    _sm.set_arbiter_freeze_hook(_on_machine_freeze)


def freeze_hook_installed() -> bool:
    """消费预演自检用：state_machine 咽喉回调是否已注册（真源在 state_machine）。"""
    from core import state_machine as _sm

    return _sm.get_arbiter_freeze_hook() is not None
