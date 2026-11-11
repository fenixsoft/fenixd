"""core/admin_auto_exec.py — 裁决告警推荐项分级自动执行策略引擎
（add-adjudication-auto-exec 2.1/2.2/2.3）。

pending 升级告警在「arbiter 完整调查产出明确推荐 + 推荐为可逆自限动作
（risk_tier=reversible-experiment）+ 同 SPEC 无共存更高档 pending + 本 SPEC
连续自动执行未超上限」四判据全过时，grace 否决窗（缺省 30 分钟，自推荐
可用时刻起算）满仍 pending 则自动执行推荐 choice——压缩「机器已有答案、
等人点击」的决策就绪后空转段（redesign-chain-panel-ui 事故：arbiter 推荐
到人工点击空转 10h14m、点击内容=机器推荐原文，全链 10h36m）。

设计约束（design.md 决策）：

- 链序不变：本引擎只改变链终点（人工出口）在「有明确推荐 + 可逆动作」时
  的等待语义；human-only 档（state-advance/terminal）继续等人，grace 窗内
  人工否决/改选先到先得。
- 执行复用既有单机器 ``execute_choice_for_disposition``（人工 alert-resolve、
  admin_monitor 直接路径、链 closed 出口、本引擎四处同源，禁复制第四份
  分支逻辑，design 决策 3）。
- grace 窗状态不落盘：到期时刻 = 推荐可用时刻 + grace，读时计算（design
  决策 4）。推荐可用时刻取告警 ``arbiter_upgrade.upgraded_at``（arbiter
  调查完成、推荐落账时刻；告警创建与推荐落账异步，锚 created 会使异步
  升级件否决窗归零），无 upgrade 痕回退 ``created``。
- 连续计数从处置留痕按 actor 派生，不新增状态文件（design 决策 5）。
- fail-open：任何异常单条捕获记日志本轮跳过；enabled=false 整体停用回退
  纯人工语义（design 决策 7）；引擎永不阻塞其他车道。

推荐解析机械约定（判据①后半）：对告警 ``choices[]`` 注册 id 在
``arbiter_upgrade.recommended_action`` 文本做正向提及匹配——否定语境
（「不推荐/不选/勿选/不作为」等就近修饰）不计正向，否定词与提及之间
允许隔同级选项列表（「不推荐 force_advance/abandon」对 abandon 同样
构成否定修饰，redesign 件实证形态）；唯一正向命中方视为「推荐明确」，
零命中或多义命中一律判推荐不明确、跳过等人工（宁跳过勿误执行）。
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from core.config import ConfigLoader
from core.timelib import parse_ts

# 引擎日志通道（与 admin_monitor/event_bus 等通道命名同族）
LOG_CHANNEL = "admin_auto_exec"

# 自动执行处置留痕 actor（任务书 2.2：留痕与人工同构，仅 actor 不同）
AUTO_POLICY_ACTOR = "auto-policy"
# 老化升级活动记录 actor（2.3：只做可见性不执行动作；独立 actor 使连续
# auto-exec 计数走查中性跳过，不误计也不误重置）
AGING_ACTOR = "aging-watch"

# severity 排序（判据③「共存更高严重度」；与 admin_alerts._summary_from_
# unhandled 同一张表语义，此处独立字面量避免读层反向依赖）
_SEVERITY_RANK = {"critical": 3, "major": 2, "minor": 1}

# ── 推荐文本正向提及匹配 ────────────────────────────────────────────
# 否定语境词表（specs/adjudication-auto-exec：「不推荐/不选/勿选/不作为」
# 等否定语境就近修饰的不计正向）；同义扩展不执行/不采纳/不可选/勿执行。
_NEGATION_PHRASES = (
    "不推荐", "不建议", "不选", "勿选", "不作为", "不采纳", "不执行",
    "不可选", "勿执行",
)
# 同级选项列表分隔符（否定词与提及间允许隔「不推荐 A/B」形态的兄弟选项
# 与标点空白；句号等终结符不入表——否定语境不跨句）
_LIST_SEPARATORS = " \t\r\n/、，,；;：:|&+·()（）[]【】\"'"
# 兄弟选项跳接上限（防病态长列表线性回扫）
_SIBLING_HOP_LIMIT = 6


def parse_alert_time(value) -> "datetime | None":
    """告警时间戳 → aware datetime；缺失/非法返回 None。

    解析单源走 timelib.parse_ts（timelib-consolidation：模块外禁直调
    fromisoformat）。admin_store 写侧恒 aware UTC（to_storage 单一 ``Z``
    后缀族），aware 输入语义不变；naive 形态仅来自外部直写的历史脏数据，
    按 timelib 唯一 naive 策略本地解读（本函数原私有实现的 naive→UTC 属
    唯一策略外的第二种 naive 解读，随迁移收拢）。
    """
    return parse_ts(str(value or "").strip())


def grace_anchor(rec) -> "datetime | None":
    """推荐可用时刻单源（design 决策 4）。

    ``arbiter_upgrade.upgraded_at``（arbiter 调查完成、推荐落账时刻）优先；
    无 upgrade 痕回退告警 ``created``。两者均不可解析返回 None（调用方跳过
    本轮，宁跳过勿以错锚执行）。
    """
    upgrade = rec.get("arbiter_upgrade") if isinstance(rec, dict) else None
    if isinstance(upgrade, dict):
        ts = parse_alert_time(upgrade.get("upgraded_at"))
        if ts is not None:
            return ts
    return parse_alert_time(rec.get("created")) if isinstance(rec, dict) else None


def _mention_negated(text: str, start: int, ids: list) -> bool:
    """``text[start:]`` 处的选项提及是否被否定语境就近修饰。

    回扫规则：从提及起点向前跳过列表分隔符；命中兄弟选项 token 则跳过并
    继续回扫（「不推荐 force_advance/abandon」对 abandon 构成否定修饰）；
    跳接受 ``_SIBLING_HOP_LIMIT`` 上界。随后取紧邻前缀判否定短语后缀命中
    （rstrip 分隔符——「不推荐 X」「不推荐：X」均命中）。
    """
    i = start
    for _hop in range(_SIBLING_HOP_LIMIT):
        j = i
        while j > 0 and text[j - 1] in _LIST_SEPARATORS:
            j -= 1
        if j == i:
            break
        i = j
        sibling_hit = False
        for other in ids:
            if other and text[:i].endswith(other):
                i -= len(other)
                sibling_hit = True
                break
        if not sibling_hit:
            break
    prefix = text[:i].rstrip(_LIST_SEPARATORS)
    return any(prefix.endswith(p) for p in _NEGATION_PHRASES)


def _positive_mention_ids(ids: list, text: str) -> list:
    """推荐文本中获正向提及的选项 id 列表（保持入参序）。

    词边界匹配（``(?<![\w])…(?![\w])``）——防 ``abandon`` 子串误配更长相邻
    标识；多处提及任一处正向即计正向（否定修饰逐出现判定）。
    """
    positive = []
    for cid in ids:
        pattern = r"(?<![\w])" + re.escape(cid) + r"(?![\w])"
        for m in re.finditer(pattern, text):
            if not _mention_negated(text, m.start(), ids):
                positive.append(cid)
                break
    return positive


def extract_recommended_choice(rec) -> tuple:
    """告警记录 → ``(choice_id, 注册表解析选项, 跳过原因)``。

    判据①后半的单点实现：候选集取告警 ``choices[]`` 快照 id（发射时快照
    即该信号的裁决空间），推荐文本取 ``arbiter_upgrade.recommended_action``
    （无则回退 ``recommended_action`` 顶层字段——arbiter_upgrade 写点两者
    同步，顶层回退兜历史形态）。唯一正向命中方返回；零/多义命中返回
    ``(None, None, 原因)``。

    命中项经 ``resolve_choice`` 注册表单源复核解析（告警快照与注册表可能
    漂移——注册表后续收窄/改档时以注册表现值为准），拒绝解析按不明确
    处理。返回选项为注册表逐项拷贝（risk_tier 等档位声明随附）。
    """
    text = ""
    upgrade = rec.get("arbiter_upgrade") if isinstance(rec.get("arbiter_upgrade"), dict) else {}
    text = str(upgrade.get("recommended_action") or "").strip()
    if not text:
        text = str(rec.get("recommended_action") or "").strip()
    if not text:
        return None, None, "无推荐文本（arbiter 未落账推荐）"
    raw_choices = rec.get("choices")
    if not isinstance(raw_choices, list):
        return None, None, "告警无 choices 快照"
    entries = []
    seen_ids = set()
    for c in raw_choices:
        if isinstance(c, dict) and str(c.get("id") or "").strip():
            cid = str(c["id"]).strip()
            if cid not in seen_ids:
                seen_ids.add(cid)
                entries.append(cid)
    if not entries:
        return None, None, "告警 choices 快照为空"
    positive = _positive_mention_ids(entries, text)
    if not positive:
        return None, None, "推荐文本对全部选项零正向提及"
    if len(positive) > 1:
        return None, None, f"推荐文本正向提及多个选项（{'/'.join(positive)}），判歧义"
    cid = positive[0]
    try:
        from core.dashboard.data.adjudication_choices import resolve_choice

        resolved, reason = resolve_choice(cid, str(rec.get("signal_type") or ""))
    except Exception as e:  # noqa: BLE001 — 注册表不可用按不明确处理（fail-safe）
        return None, None, f"注册表解析异常（{e}）"
    if resolved is None:
        return None, None, f"注册表解析拒绝（{reason}）"
    return cid, resolved, ""


def auto_exec_projection(rec, grace_minutes=None) -> dict:
    """告警记录 → 自动执行展示投影（5.1 读侧透出，无 schema 变更）。

    供 Dashboard 派生 auto-executed 徽标（``executed``=handled_by 值为
    auto-policy）与 grace 倒计时（pending + 有明确推荐 + 可逆档时给出
    ``due_at``）。纯读函数，不改写记录。
    """
    cid, choice, reason = extract_recommended_choice(rec)
    anchor = grace_anchor(rec)
    executed = (
        isinstance(rec, dict)
        and str(rec.get("handled_by") or "") == AUTO_POLICY_ACTOR
    )
    due_iso = None
    if anchor is not None and cid and grace_minutes:
        try:
            due = anchor + timedelta(minutes=int(grace_minutes))
            due_iso = due.isoformat()
        except (TypeError, ValueError, OverflowError):
            due_iso = None
    from core.dashboard.data.adjudication_choices import choice_risk_tier

    return {
        "recommended_choice": cid,
        "risk_tier": choice_risk_tier(choice) if choice else None,
        "skip_reason": reason or None,
        "anchor_at": anchor.isoformat() if anchor else None,
        "due_at": due_iso,
        "executed": executed,
    }


class AdminAutoExecEngine:
    """pending 升级告警推荐项分级自动执行策略引擎（daemon 侧扫描环）。

    60s 轻量扫描（文件读 + 内存判据，design 决策 2）：逐条 pending 告警
    跑老化升级（2.3，可见性）与自动执行判定（2.1/2.2）；异常单条捕获
    隔离，永不阻塞其他车道。
    """

    INTERVAL_SECONDS = 60

    def __init__(self, config, project_root, logger, store=None,
                 interval_seconds=None):
        self.config = config
        self.project_root = project_root
        self.logger = logger
        self._store = store
        self.interval_seconds = max(5, int(interval_seconds or self.INTERVAL_SECONDS))
        self._stop_event = threading.Event()
        self._thread = None
        self._disabled_logged = False

    # ── 生命周期 ────────────────────────────────────────────────────

    @property
    def store(self):
        """AdminStore（装配注入优先；缺省按 project_root 自建纯路径实例）。"""
        if self._store is None:
            from core.admin_store import AdminStore

            self._store = AdminStore(self.project_root, self.logger)
        return self._store

    def start(self):
        """启动后台扫描线程（daemon 线程；重复 start 复用存活线程）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="fenixd-admin-auto-exec", daemon=True,
        )
        self._thread.start()
        self.logger.info(
            LOG_CHANNEL,
            f"裁决自动执行策略引擎已启动（扫描间隔 {self.interval_seconds}s）",
        )

    def stop(self):
        """收口扫描线程（daemon 收尾调用；有界 join 不阻塞关停）。"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _loop(self):
        # 首轮先睡一个间隔：避让 daemon 启动风暴，也让 pending 告警的
        # grace 判定基于稳定读数（错峰对齐其它后台环形态）
        if self._stop_event.wait(self.interval_seconds):
            return
        while not self._stop_event.is_set():
            try:
                self.scan_once()
            except Exception as e:  # noqa: BLE001 — 整轮兜底，引擎永不带崩主进程
                try:
                    self.logger.error(
                        LOG_CHANNEL, f"扫描轮异常（fail-open 本轮放弃）: {e}",
                    )
                except Exception:  # pragma: no cover — 日志通道死亡不再上抛
                    pass
            self._stop_event.wait(self.interval_seconds)

    # ── 扫描主流程 ──────────────────────────────────────────────────

    def scan_once(self) -> int:
        """单轮扫描：返回本轮实际自动执行次数（供测试断言/手动触发）。

        enabled=false 整体停用（零动作零噪音，回退纯人工语义）；存储读
        失败整轮放弃；单告警判定异常捕获隔离。
        """
        cfg = ConfigLoader.get_auto_exec_config(self.config)
        if not cfg.get("enabled"):
            if not self._disabled_logged:
                self._disabled_logged = True
                self.logger.info(
                    LOG_CHANNEL, "auto_exec.enabled=false，引擎停用（纯人工语义）",
                )
            return 0
        self._disabled_logged = False
        try:
            records = self.store.read_all()
        except Exception as e:  # noqa: BLE001 — 读失败整轮放弃
            self.logger.warning(LOG_CHANNEL, f"告警存储读取失败本轮跳过: {e}")
            return 0
        pending = [
            r for r in records
            if r.get("kind") == "escalation" and not r.get("handled")
        ]
        executed = 0
        for rec in pending:
            try:
                if self._process_alert(rec, records, pending, cfg):
                    executed += 1
            except Exception as e:  # noqa: BLE001 — 单条隔离（design 决策 7）
                self.logger.error(
                    LOG_CHANNEL,
                    f"告警 {rec.get('id')} 判定异常本轮跳过: "
                    f"{type(e).__name__}: {e}",
                )
        return executed

    def _process_alert(self, rec, records, pending, cfg) -> bool:
        """单告警处理：老化升级（可见性）+ 自动执行判定。返回是否执行。

        老化去重须扫全量 ``records``（老化标记落 DISPOSITION 记录，不在
        pending 升级件集合内）；冲突判定只看同轮 ``pending`` 升级件。
        """
        self._maybe_aging_escalate(rec, cfg, records)
        return self._maybe_auto_exec(rec, pending, cfg)

    # ── 2.1/2.2：自动执行判定与到点执行 ─────────────────────────────

    def _maybe_auto_exec(self, rec, pending, cfg) -> bool:
        """四判据全过且 grace 窗满 → 执行推荐 choice。返回是否执行。"""
        alert_id = str(rec.get("id") or "")
        spec = str(rec.get("spec") or "")
        # 判据①前半：arbiter 完整调查痕 + 推荐文本已落账（arbiter_upgrade
        # 原位升级写点同时携带两者；缺任一 = 调查未完成，静默等人工）
        upgrade = rec.get("arbiter_upgrade")
        if not (
            isinstance(upgrade, dict)
            and str(upgrade.get("recommended_action") or "").strip()
        ):
            self.logger.debug(
                LOG_CHANNEL,
                f"告警 {alert_id} 无 arbiter 完整调查/推荐痕，等待人工",
            )
            return False
        # grace 窗（design 决策 4）：到期 = 推荐可用时刻 + grace_minutes
        anchor = grace_anchor(rec)
        if anchor is None:
            self.logger.warning(
                LOG_CHANNEL,
                f"告警 {alert_id} 时间戳不可解析（upgraded_at/created 均非法），跳过",
            )
            return False
        grace = timedelta(minutes=int(cfg.get("grace_minutes") or 30))
        due = anchor + grace
        if datetime.now(timezone.utc) < due:
            self.logger.debug(
                LOG_CHANNEL,
                f"告警 {alert_id} grace 窗未满（到期 {due.isoformat()}），跳过",
            )
            return False
        # 判据①后半：唯一正向命中方为「推荐明确」
        cid, choice, reason = extract_recommended_choice(rec)
        if cid is None:
            self.logger.info(
                LOG_CHANNEL, f"告警 {alert_id} 推荐不明确（{reason}），跳过等人工",
            )
            return False
        # 判据②：推荐档位须为可逆自限档（缺档 terminal 兜底已在取档单点）
        from core.dashboard.data.adjudication_choices import (
            RISK_TIER_REVERSIBLE,
            choice_risk_tier,
        )

        tier = choice_risk_tier(choice)
        if tier != RISK_TIER_REVERSIBLE:
            self.logger.info(
                LOG_CHANNEL,
                f"告警 {alert_id} 推荐 {cid} 档位 {tier} 非 reversible-experiment，"
                "不自动执行等人工",
            )
            return False
        # 载荷门：requires_payload 选项自动通道无载荷，必然执行失败——前置跳过
        if bool(choice.get("requires_payload", False)):
            self.logger.info(
                LOG_CHANNEL,
                f"告警 {alert_id} 推荐 {cid} 为 requires_payload 选项且自动通道"
                "无载荷，跳过等人工",
            )
            return False
        # 全局形态守卫（执行机器同款消费端防线的前置）：spec_scoped 动作对
        # 全局信号无 spec 可操作
        from core.dashboard.data.adjudication_choices import is_global_spec

        if bool(choice.get("spec_scoped", True)) and is_global_spec(spec):
            self.logger.info(
                LOG_CHANNEL,
                f"告警 {alert_id} 推荐 {cid} 为 spec 作用域动作而信号为全局形态"
                f"（spec={spec!r}），跳过",
            )
            return False
        # 判据③：同 SPEC 无共存更高风险档 pending 告警
        conflict = self._higher_risk_conflict(rec, choice, pending)
        if conflict:
            self.logger.info(
                LOG_CHANNEL,
                f"告警 {alert_id} 同 SPEC 存在共存更高档 pending 告警（{conflict}），"
                "跳过等人工一并处置",
            )
            return False
        # 判据④：本 SPEC 连续自动执行 < cap
        cap = int(cfg.get("consecutive_max") or 2)
        streak = self._consecutive_auto_exec(spec)
        if streak >= cap:
            self.logger.info(
                LOG_CHANNEL,
                f"spec '{spec or '（全局）'}' 连续自动执行已 {streak} 次"
                f"（cap={cap}），转纯人工等待",
            )
            return False
        return self._execute(rec, cid, choice)

    def _higher_risk_conflict(self, rec, choice, pending) -> str:
        """判据③：返回共存更高档说明串（无共存返回空串）。

        「更高档」两路判据（design Open Questions 已核实口径）：共存 pending
        告警 severity 更高，或其选项集（经注册表读时解析）最高 risk_tier
        高于推荐档。两路任一命中即冲突——多件 pending 并存时整体让人工
        一并裁决，避免机器只看到局部。
        """
        spec = str(rec.get("spec") or "")
        if not spec:
            return ""  # 全局信号无「同 SPEC」共存概念
        from core.dashboard.data.adjudication_choices import (
            RISK_TIERS,
            choice_risk_tier,
            resolve_choice,
        )

        my_sev = _SEVERITY_RANK.get(str(rec.get("severity") or ""), 0)
        my_tier_rank = RISK_TIERS.index(choice_risk_tier(choice))
        self_id = str(rec.get("id") or "")
        for other in pending:
            if str(other.get("id") or "") == self_id:
                continue
            if str(other.get("spec") or "") != spec:
                continue
            if _SEVERITY_RANK.get(str(other.get("severity") or ""), 0) > my_sev:
                return f"severity 更高的 {other.get('id')}"
            for c in (other.get("choices") or []):
                if not isinstance(c, dict):
                    continue
                resolved, _ = resolve_choice(
                    str(c.get("id") or ""), str(other.get("signal_type") or ""),
                )
                other_rank = RISK_TIERS.index(choice_risk_tier(resolved or c))
                if other_rank > my_tier_rank:
                    return f"更高档选项的 {other.get('id')}"
        return ""

    def _consecutive_auto_exec(self, spec: str) -> int:
        """本 SPEC 连续自动执行计数（判据④；处置留痕派生，零状态文件）。

        从最新处置留痕向前数 actor=auto-policy 连续段；人工/链出口留痕
        （无 actor 字段）中断计数；aging-watch 与 pending 在飞标记记录
        中性跳过（不是处置动作，不误计也不误重置）。
        """
        if not spec:
            return 0
        try:
            records = self.store.read_all()
        except Exception:  # noqa: BLE001 — 计数不可得按 0 放行（执行器仍守约）
            return 0
        disp = [
            r for r in records
            if r.get("kind") == "disposition"
            and str(r.get("spec") or "") == spec
        ]
        # created 字典序即时间序（AdminStore 写侧 UTC 单一后缀族同款口径）
        disp.sort(key=lambda r: str(r.get("created") or ""))
        count = 0
        for r in reversed(disp):
            actor = str(r.get("actor") or "")
            status = str(r.get("status") or r.get("result") or "")
            if actor == AGING_ACTOR or status == "pending":
                continue
            if actor == AUTO_POLICY_ACTOR:
                count += 1
                continue
            break
        return count

    def _execute(self, rec, cid, choice) -> bool:
        """到点执行（2.2）：瞬时重读 → 单机器执行 → 留痕 → 闭环告警。"""
        alert_id = str(rec.get("id") or "")
        spec = str(rec.get("spec") or "")
        signal_type = str(rec.get("signal_type") or "")
        # 执行前瞬时重读（grace 窗竞态防线）：窗口内人工已处理（alert-resolve
        # 任一 choice / 标记已处理）即让位——先到先得，不产生重复处置留痕
        fresh = self._fresh_record(alert_id)
        if fresh is None:
            self.logger.info(
                LOG_CHANNEL, f"告警 {alert_id} 执行前重读已不存在，跳过",
            )
            return False
        if fresh.get("handled"):
            self.logger.info(
                LOG_CHANNEL,
                f"告警 {alert_id} 窗口内已被人工处理，跳过自动执行（先到先得）",
            )
            return False
        try:
            from core.admin_choice_exec import execute_choice_for_disposition
        except Exception as e:  # noqa: BLE001 — 执行机器不可用按失败放弃本轮
            self.logger.error(
                LOG_CHANNEL, f"执行机器导入失败 alert={alert_id}: {e}",
            )
            return False
        basis = (
            f"auto-exec: arbiter 推荐 {cid}，grace 窗满自动执行"
            f"（触发告警 {alert_id}）"
        )
        disp = SimpleNamespace(
            choice_id=cid,
            choice_payload="",  # 可逆档均为非载荷选项（前置门已拦）
            actions_taken=basis,
            spec=spec,
            problem=str(fresh.get("description") or ""),
            run_id="",
        )
        signal = {"signal_type": signal_type, "spec": spec, "alert_id": alert_id}
        try:
            outcome = execute_choice_for_disposition(
                self.project_root, signal, disp, self.logger,
            )
        except Exception as e:  # noqa: BLE001 — 执行异常按失败留痕，不穿透
            self.logger.error(
                LOG_CHANNEL, f"自动执行异常 choice={cid} spec='{spec}': {e}",
            )
            outcome = {"ok": False, "skipped": False, "action": None,
                       "error": f"自动执行异常: {e}", "steps": []}
        if outcome is None or bool(outcome.get("skipped")):
            # 跳过形态未执行任何动作：不落留痕不闭环，告警保持 pending
            self.logger.info(
                LOG_CHANNEL,
                f"告警 {alert_id} 执行器跳过（{str((outcome or {}).get('error') or '未执行')}），"
                "保持 pending 等人工",
            )
            return False
        ok = bool(outcome.get("ok"))
        action = str(outcome.get("action") or cid)
        error = str(outcome.get("error") or "")
        # 留痕与人工同构（DISPOSITION 记录同字段形态，design 决策 3）：
        # 仅 actor=auto-policy 与触发告警 id 不同；无 admin_run_id（循逐动作
        # 记录先例，不破坏在飞 = has_pending 判据）
        try:
            from core.admin_store import DISPOSITION

            self.store.append({
                "kind": DISPOSITION,
                "signal_type": signal_type,
                "spec": spec,
                "severity": fresh.get("severity"),
                "description": str(fresh.get("description") or ""),
                "action_taken": action,
                "result": "resolved" if ok else "failed",
                "error": "" if ok else (error or "执行失败"),
                "actor": AUTO_POLICY_ACTOR,
                "alert_id": alert_id,
                "choice_id": cid,
                "auto_exec": True,
            })
        except Exception as e:  # noqa: BLE001 — 留痕失败不阻塞闭环主链路
            self.logger.error(
                LOG_CHANNEL, f"自动执行留痕写入失败 alert={alert_id}: {e}",
            )
        if ok:
            self._close_alert(alert_id, action)
            self.logger.info(
                LOG_CHANNEL,
                f"自动执行成功 choice={cid} spec='{spec}' alert={alert_id} "
                f"(actor={AUTO_POLICY_ACTOR})",
            )
        else:
            # 失败不闭环：告警保持 pending 等人工（宁重复告警不静默）
            self.logger.error(
                LOG_CHANNEL,
                f"自动执行失败 choice={cid} spec='{spec}': {error or '执行失败'}"
                f"，告警保持 pending",
            )
        return ok

    def _fresh_record(self, alert_id: str):
        """按 id 瞬时重读告警记录（执行前竞态检查用；读失败按缺失处理）。"""
        try:
            records = self.store.read_all()
        except Exception:  # noqa: BLE001 — 读失败按缺失处理（宁可不做不误做）
            return None
        return next(
            (r for r in records if str(r.get("id") or "") == alert_id), None,
        )

    def _close_alert(self, alert_id: str, action: str) -> bool:
        """自动执行成功后的告警闭环：handled_by=auto-policy（5.1 徽标派生键）。

        经 ``update_records`` 公开批量改写入口单次排他锁内闭环（仅未处理
        ESCALATION 条目生效——人工先到先得在本写点同样成立，幂等）。
        """
        from core.admin_store import ESCALATION

        def mutate(records):
            changed = False
            for r in records:
                if (
                    r.get("id") == alert_id
                    and r.get("kind") == ESCALATION
                    and not r.get("handled")
                ):
                    r["handled"] = True
                    r["handled_at"] = datetime.now(timezone.utc).isoformat()
                    r["handled_by"] = AUTO_POLICY_ACTOR
                    r["action_taken"] = action
                    changed = True
            return changed

        try:
            return bool(self.store.update_records(mutate))
        except Exception as e:  # noqa: BLE001 — 闭环失败留痕不静默
            self.logger.error(
                LOG_CHANNEL, f"告警 {alert_id} 闭环写回失败: {e}",
            )
            return False

    # ── 2.3：human-only 档老化升级 ──────────────────────────────────

    def _maybe_aging_escalate(self, rec, cfg, records) -> None:
        """pending 超阈值（2h/6h 两档）的 human-only 告警写升级活动记录。

        只做可见性不执行动作（design 决策 8）。定档口径与自动执行一致
        （唯一正向命中的推荐档位）；推荐歧义/无调查痕的告警语义未定档，
        不写（避免不可判件刷屏）。同告警同档去重（引擎 60s 一轮，不去重
        会每分钟刷一条）；warning→critical 随老化递进各记一条。
        """
        cid, choice, _reason = extract_recommended_choice(rec)
        if cid is None:
            return
        from core.dashboard.data.adjudication_choices import (
            RISK_TIER_REVERSIBLE,
            choice_risk_tier,
        )

        tier = choice_risk_tier(choice)
        if tier == RISK_TIER_REVERSIBLE:
            return  # 可逆档由 grace 窗自动执行语义负责，不走老化升级
        created = parse_alert_time(rec.get("created"))
        if created is None:
            return
        age_min = (datetime.now(timezone.utc) - created).total_seconds() / 60.0
        warn = int(cfg.get("aging_warning_minutes") or 120)
        crit = int(cfg.get("aging_critical_minutes") or 360)
        if age_min >= crit:
            level, minutes, severity = "critical", crit, "critical"
        elif age_min >= warn:
            level, minutes, severity = "warning", warn, "major"
        else:
            return
        alert_id = str(rec.get("id") or "")
        marker = f"aging-escalated:{level}"
        # 去重：已读记录单次遍历（本轮读数即权威——写点唯一为本引擎）
        for r in records:
            if (
                r.get("kind") == "disposition"
                and str(r.get("alert_id") or "") == alert_id
                and str(r.get("action_taken") or "") == marker
            ):
                return
        try:
            from core.admin_store import DISPOSITION

            self.store.append({
                "kind": DISPOSITION,
                "signal_type": rec.get("signal_type"),
                "spec": rec.get("spec"),
                "severity": severity,
                "description": (
                    f"告警老化升级（{level}）：pending 超 {minutes} 分钟仍未"
                    f"人工处置（推荐 {cid}，{tier} 档不自动执行，等人工）"
                ),
                "action_taken": marker,
                "result": "aging",
                "actor": AGING_ACTOR,
                "alert_id": alert_id,
                "choice_id": cid,
            })
        except Exception as e:  # noqa: BLE001 — 可见性写点失败不影响主流程
            self.logger.warning(
                LOG_CHANNEL, f"老化升级活动记录写入失败 alert={alert_id}: {e}",
            )
            return
        self.logger.warning(
            LOG_CHANNEL,
            f"human-only 告警 {alert_id} 老化升级（{level}，pending "
            f"{int(age_min)} 分钟，推荐 {cid}/{tier}）——只做可见性，等人工",
        )
