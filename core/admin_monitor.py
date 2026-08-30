"""
admin_monitor.py — 轻量健康监视器（零 LLM 成本）。

daemon 内独立线程周期性读取本地数据（STATE.md、.fenix/runs/ 转录、fenixd.log），
按规则检测 Agent 无法自行脱困的困境信号。检测到困境且节流通过时，
回调 agent_runner 唤起 Administrator Agent（见 administrator-agent spec）。

检测规则（design D2 / admin-health-monitor spec）：
  - repeated_failures  窗口内同 spec 失败 run ≥ 阈值（默认 30 分钟 ≥3 次）
  - flapping           窗口内同 spec ready↔implementing 状态切换 ≥ 阈值（默认 10 分钟 ≥3 次）
  - stuck              implementing/testing 超 stuck_threshold_minutes 且无 run 进度
  - merge_streak       _merge_streak 已达熔断阈值仍滞留（merge-back 反复失败）
  - daemon_errors      fenixd.log 尾部连续 ERROR ≥ 阈值

节流（D2）：同 spec 同类信号在 admin.escalation_cooldown_minutes 内只唤起一次，
依据 .fenix/admin_alerts.json 中的 signal 记录与未处理升级告警。

纯本地数据、零 LLM：本模块任何路径都不调用 claude / LLM API。
"""

import json
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .admin_store import AdminStore, SIGNAL, ESCALATION, DISPOSITION
from .alert_lifecycle import attach_trigger

# 默认阈值（design D2）
REPEAT_FAILURE_WINDOW_MINUTES = 30
REPEAT_FAILURE_THRESHOLD = 3
FLAPPING_WINDOW_MINUTES = 10
FLAPPING_THRESHOLD = 3
DAEMON_ERROR_THRESHOLD = 3
STUCK_GRACE_MINUTES = 10  # run 文件 mtime 距现在小于此值视为"有进度"，不算卡死
RESTART_REQUEST_TIMEOUT_MINUTES = 10  # restart_request 超时未清除 → 重启失败 → 升级

# family_explosion 放行文本兜底：仅当处置文本表达「显式放行」语义时才写豁免位。
# 2026-08-28 实证（fix-fix-fix-add-spec-context-menu）：旧的「包含 _family_waiver/
# 放行/waive 令牌即放行」宽松匹配，把处置叙述中否定句里的字面令牌（如
# 「明确不发放 _family_waiver」）误判为放行动作，给未放行的父 SPEC 错误写入
# _family_waiver=true。改为：命中否定短语即不放行；否则须命中赋值型/明确动词型
# 放行模式才写位。
# 2026-08-28 二次实证（fix-fix-fix-improve-failover-model-mapping-ui，admin run
# 1787945929）：否定清单缺「未发放/未放行」等完成时否定，且赋值型模式命中了处置
# 叙述里对【另一族谱】豁免位的提及（「全库唯一的 _family_waiver=true 在另一族谱」
# ——与本困境无关），双重误判给已终态父 SPEC 错误写入 _family_waiver=true。
# 修正：a) 否定清单补完成时/委婉否定；b) 赋值型/动词型模式须与「放行」动词在同句
# 才算放行（单纯提及字段名/他族谱状态不构成放行）。
_WAIVER_NEGATION_PHRASES = (
    "未放行", "不放行", "拒绝放行", "不予放行", "不发放", "未发放",
    "不启用豁免", "未启用豁免", "不予豁免", "无须放行", "无需放行", "不必放行",
)
_WAIVER_GRANT_PATTERNS = (
    r"同意放行",
    r"放行一次",
    r"经评估放行",
    r"设置\s*_family_waiver\s*为?\s*true",  # 设置 _family_waiver 为 true
)
# 赋值型 _family_waiver=true 必须与放行动词同句（。！？\n 分句）才算显式放行，
# 防止叙述中对字段名/其他族谱豁免状态的提及被误判为本次处置的放行动作。
_WAIVER_ASSIGN_RE = re.compile(r"_family_waiver['\"]?\s*[=:：]\s*['\"]?true")

# 「写入即待唤起」信号的终态守卫：spec 已达这些状态时不再唤起 Administrator
# （done/pushed 之后族谱不可能再派生，困境实质已消失）。
_TERMINAL_SPEC_STATUSES = ("done", "pushed")

# 信号 → 严重度/建议处置
SIGNAL_SEVERITY = {
    "repeated_failures": "major",
    "flapping": "major",
    "stuck": "major",
    "merge_streak": "critical",
    "blocked_stuck": "critical",
    "daemon_errors": "critical",
    "family_explosion": "major",
    "dispatch_stalled": "major",
}
SIGNAL_RECOMMENDATION = {
    "repeated_failures": "检查重复失败的根因（如构建/测试命令错误），必要时重置 spec 状态或修复框架配置",
    "flapping": "检查 spec 状态机空转回路（ready↔implementing），修复派发/恢复逻辑或人工介入",
    "stuck": "检查卡死 Agent 子进程（kill 并按需重启），或重置 spec 状态重新调度",
    "merge_streak": "检查 merge-back 冲突根因（stash/分支冲突），清理 git 状态后重新 merge",
    "blocked_stuck": "检查 blocked 是否误置（误判派生的假 spec）或确需人工决策；清理假 spec 或重置后重新调度，必要时升级",
    "daemon_errors": "检查 fenixd 连续 ERROR 的根因，必要时重启 daemon",
    "family_explosion": "检修根因环境（如验证报告互相咬合导致 fix 递归）；确认放行一次则对父 SPEC 设置 _family_waiver=true",
    "dispatch_stalled": "检查持锁进程是否为孤儿（ps/pgrep 确认后 kill），清理残留 worktree 锁后让 spec 重新派发",
}

# pm_engine 直接写入 store、由本监视器摄取唤起的信号类型（写入即待唤起型）。
# family_explosion 既有；dispatch_stalled 属 run 生命周期治理（锁冲突退避耗尽 /
# 恢复闭环复查未通过）。
STORED_SIGNAL_TYPES = ("family_explosion", "dispatch_stalled")

# run_id 前缀 → 计入"失败 run"的 agent 类型
_RUN_PREFIXES = ("impl-", "verify-", "planner-plan-", "planner-judge-", "admin-")


class AdminMonitor:
    """困境信号检测 + 节流 + 唤起调度。run_once() 为单次检测入口。"""

    def __init__(self, config: dict, state_machine, project_root, logger,
                 store=None, agent_runner=None):
        from .config import ConfigLoader
        self.config = config
        self.admin_cfg = ConfigLoader.get_admin_config(config)
        self.state_machine = state_machine
        self.project_root = Path(project_root)
        self.logger = logger
        self.store = store if store is not None else AdminStore(self.project_root, logger)
        # agent_runner 提供 run_administrator(signal)；None 时只检测、不唤起（测试/禁用态）
        self.agent_runner = agent_runner
        self._history_path = self.project_root / ".fenix" / "admin_state_history.json"

    # ── 配置读取 ────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return bool(self.admin_cfg["enabled"])

    @property
    def interval_minutes(self) -> float:
        return float(self.admin_cfg["interval_minutes"])

    @property
    def cooldown_minutes(self) -> float:
        return float(self.admin_cfg["escalation_cooldown_minutes"])

    def _get_config(self, key: str, default=None):
        from .config import ConfigLoader
        return ConfigLoader.get(self.config, key, default)

    # ── 主入口 ──────────────────────────────────────────────────

    def has_in_progress_specs(self) -> bool:
        """是否存在进行中 spec（implementing/testing）——检测前置条件。"""
        for entry in self.state_machine.read_all().values():
            if entry.get("status") in ("implementing", "testing"):
                return True
        return False

    def run_once(self) -> list:
        """执行一次完整检测：识别信号 → 记录 → 节流判定 → 唤起 Administrator。

        返回本次检测到的信号列表（供测试/审计）。
        """
        if not self.enabled:
            return []

        # 族谱爆炸信号由 pm_engine 在拦截时直接写入 store（父 SPEC 保持 bug-found，
        # 不满足 has_in_progress_specs 门控，却同样需要送达 Administrator）。
        # 该摄取在门控之前完成：_detect_family_explosion 内部直接唤起 Administrator
        # 并把源记录标记 escalated，返回仅供审计/测试（不再经 _handle_signal 节流，
        # 否则 pm_engine 刚写入的 SIGNAL 记录会被 latest_signal 误判为「已唤起」）。
        family_signals = self._detect_family_explosion()

        if not self.has_in_progress_specs():
            # 假就绪盲区修复（improve-run-lifecycle-governance D6）：无 in-progress
            # spec 只说明没有运行态任务，MUST NOT 成为跳过整轮巡检的理由——
            # ready 滞留（假就绪）、blocked_stuck、daemon_errors 等非运行态检查
            # 仍然必须执行（2026-08-27 事故：假 ready 滞留近 1 小时无人发现）。
            self.logger.debug(
                "admin_monitor",
                "No in-progress SPECs — continuing non-running-state scans",
            )

        specs = self.state_machine.read_all()
        now = time.time()
        regular = self._detect(specs, now)

        for signal in regular:
            self._handle_signal(signal)

        # fix-admin-self-heal：孤儿处置与重启失败的兜底升级（非 per-spec 信号）
        self._recover_orphaned_dispositions()
        self._detect_restart_failure(now)
        return family_signals + regular

    # ── 检测规则 ────────────────────────────────────────────────

    def _detect(self, specs: dict, now: float) -> list:
        """运行全部检测规则，返回信号列表。"""
        signals = []
        signals.extend(self._detect_repeated_failures(specs, now))
        signals.extend(self._detect_flapping(specs, now))
        signals.extend(self._detect_stuck(specs, now))
        signals.extend(self._detect_merge_streak(specs))
        signals.extend(self._detect_blocked_stuck(specs, now))
        signals.extend(self._detect_daemon_errors(now))
        return signals

    def _detect_blocked_stuck(self, specs: dict, now: float) -> list:
        """blocked 状态超时未处理 → 唤起 admin 处置（fix-admin-self-heal）。

        熔断把 spec 置 blocked 后等待人工；但部分 blocked 是误置（如误判派生的
        假 spec），且人工未必及时看到。超过阈值仍滞留 → 交给 admin 判定是清理
        还是升级。
        """
        signals = []
        threshold = max(self.cooldown_minutes, 15)
        for name, entry in specs.items():
            if entry.get("status") != "blocked":
                continue
            # 冻结豁免：Administrator 为去重/家族收敛而人为冻结的 spec（error 前缀
            # 'frozen:'），其 blocked 是有意保持的等待态，updated 不会推进——按超时
            # 唤起只会形成每轮重复误报。真实停滞仍由 stuck/repeated_failures/
            # family_explosion 等规则覆盖。
            # 用户指令暂停（2026-08-30 v2-acceptance-suite 误报）：人工处置时直接
            # 写入的「用户指令暂停：…」同样是有意等待态，等价于 frozen——人工历史
            # 文案未必带 frozen: 前缀，故按子串识别，双保险。
            err = str(entry.get("error") or "")
            if err.startswith("frozen:") or "用户指令暂停" in err:
                self.logger.debug(
                    "admin_monitor",
                    f"Skipping blocked_stuck for intentionally-paused SPEC '{name}'",
                )
                continue
            updated_str = entry.get("updated") or entry.get("created") or ""
            try:
                updated = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            elapsed = (now - updated.timestamp()) / 60
            if elapsed <= threshold:
                continue
            signals.append(self._make_signal(
                "blocked_stuck", name,
                f"'{name}' 处于 blocked 超过 {int(elapsed)} 分钟未处理",
                f"updated={updated_str}，阈值 {threshold} 分钟",
            ))
        return signals

    def _detect_family_explosion(self) -> list:
        """摄取 pm_engine 直接写入 store 的「写入即待唤起」信号并唤起 Administrator。

        pm_engine 在族谱越界拦截时（design D4）与锁冲突退避耗尽 / 恢复闭环复查
        未通过时（improve-run-lifecycle-governance D5/D6）向 admin store 写入
        kind=SIGNAL 记录（family_explosion / dispatch_stalled），但常规检测规则
        只读 STATE/runs，不会发现它们；且 pm_engine 没有 agent_runner，无法自唤起。
        本规则在 run_once 中摄取这批记录（STORED_SIGNAL_TYPES）：
        - 每条未 escalated 的记录 → 转为信号、标记 escalated、直接唤起 Administrator
          （family_explosion 处置可对父 SPEC 放行一次 → _family_waiver）。
        - 已 escalated 的记录跳过（同记录不反复唤起）。

        返回本次摄取的信号列表（仅审计/测试用；唤起动作在内部完成）。
        """
        signals = []
        for rec in self.store.read_all():
            if rec.get("kind") != SIGNAL:
                continue
            if rec.get("signal_type") not in STORED_SIGNAL_TYPES:
                continue
            if rec.get("escalated"):
                continue  # 已唤起过，跳过
            spec = rec.get("spec")
            if not spec:
                continue
            stype = rec.get("signal_type")
            # 终态守卫（fix-family-explosion-loop 2026-08-28）：信号指向的 spec 若已
            # 终态（done/pushed），困境实质已消失——族谱成员均已合并推送、无派生口子
            # 可开，唤起 Administrator 只会得到「已收敛」的重复处置（实证：同一天
            # fix-fix-fix-improve-failover 族谱因一条陈旧未 escalated 的 SIGNAL 记录
            # 被连续唤起 4 次）。直接标记 escalated 跳过，下一 tick 不再重捞。
            try:
                spec_entry = self.state_machine.read_one(spec) or {}
            except Exception:
                spec_entry = {}
            if (spec_entry.get("status") or "") in _TERMINAL_SPEC_STATUSES:
                marked = self.store.mark_escalated(rec.get("id"))
                self.logger.info(
                    "admin_monitor",
                    f"{stype}: spec '{spec}' 已终态"
                    f"（status={spec_entry.get('status')}），跳过唤起"
                    f"（mark_escalated={'ok' if marked else '未命中'}）",
                )
                continue
            signal = self._make_signal(
                stype, spec,
                rec.get("description") or (
                    "fix 族谱越界派生被拦截" if stype == "family_explosion"
                    else "派发长期被 worktree 锁冲突滞留"
                ),
                rec.get("evidence") or "拦截详情见 pm_engine 日志",
            )
            signals.append(signal)
            # 先落 escalated 再唤起：即使唤起过程异常中止，下一 tick 也会跳过该记录
            marked = self.store.mark_escalated(rec.get("id"))
            if not marked:
                # 留痕：mark 未命中意味着该记录下一 tick 会被重捞，可能形成重复唤起
                self.logger.warning(
                    "admin_monitor",
                    f"{stype}: mark_escalated 未命中记录 id={rec.get('id')}"
                    f"（spec={spec}），该记录可能被反复摄取",
                )
            self.logger.warning(
                "admin_monitor",
                f"{stype}: invoking Administrator for '{spec}'",
                {"signal": signal},
            )
            self._invoke_administrator(signal, rec)
        return signals

    def _make_signal(self, signal_type: str, spec, description: str, evidence: str) -> dict:
        return {
            "signal_type": signal_type,
            "spec": spec,
            "severity": SIGNAL_SEVERITY.get(signal_type, "major"),
            "description": description,
            "evidence": evidence,
            "recommended_action": SIGNAL_RECOMMENDATION.get(signal_type, ""),
        }

    def _detect_repeated_failures(self, specs: dict, now: float) -> list:
        """窗口内同 spec 失败 run ≥ 阈值。"""
        signals = []
        window = REPEAT_FAILURE_WINDOW_MINUTES * 60
        cutoff = now - window
        runs_dir = self.project_root / ".fenix" / "runs"
        if not runs_dir.is_dir():
            return signals
        try:
            files = list(runs_dir.glob("*.jsonl"))
        except OSError:
            return signals

        per_spec: dict = {}
        for p in files:
            mtime = p.stat().st_mtime
            if mtime < cutoff:
                continue
            spec = self._spec_from_run_id(p.stem)
            if not spec:
                continue
            if self._run_terminal_status(p) != "error":
                continue
            per_spec.setdefault(spec, 0)
            per_spec[spec] += 1

        for spec, count in per_spec.items():
            if count >= REPEAT_FAILURE_THRESHOLD:
                signals.append(self._make_signal(
                    "repeated_failures", spec,
                    f"'{spec}' 在 {REPEAT_FAILURE_WINDOW_MINUTES} 分钟内出现 {count} 次失败 run",
                    f"最近失败 run ≥{REPEAT_FAILURE_THRESHOLD}（{count} 次），窗口 {REPEAT_FAILURE_WINDOW_MINUTES} 分钟",
                ))
        return signals

    def _detect_flapping(self, specs: dict, now: float) -> list:
        """窗口内 ready↔implementing 切换 ≥ 阈值。

        依赖 .fenix/admin_state_history.json 中本监视器各周期记录的状态变更历史
        （每次检测把当前快照与上次对比，状态变化才追加一条）。
        """
        self._update_history(specs, now)
        history = self._load_history()
        window = FLAPPING_WINDOW_MINUTES * 60
        cutoff = now - window
        signals = []
        for spec, rec in history.items():
            changes = rec.get("changes") if isinstance(rec, dict) else None
            if not changes:
                continue
            in_window = [c for c in changes if c[0] >= cutoff]
            if len(in_window) < 2:
                continue
            transitions = len(in_window) - 1
            if transitions >= FLAPPING_THRESHOLD:
                seq = " → ".join(c[1] for c in in_window[-FLAPPING_THRESHOLD:])
                signals.append(self._make_signal(
                    "flapping", spec,
                    f"'{spec}' 在 {FLAPPING_WINDOW_MINUTES} 分钟内 ready↔implementing 切换 {transitions} 次",
                    f"状态序列: {seq}",
                ))
        return signals

    def _detect_stuck(self, specs: dict, now: float) -> list:
        """implementing/testing 超阈值无 run 进度。"""
        signals = []
        threshold_minutes = self.admin_cfg["stuck_threshold_minutes"]
        grace_minutes = max(STUCK_GRACE_MINUTES, self.interval_minutes * 2)
        runs_dir = self.project_root / ".fenix" / "runs"
        for name, entry in specs.items():
            status = entry.get("status")
            if status not in ("implementing", "testing"):
                continue
            updated_str = entry.get("updated") or entry.get("created") or ""
            try:
                updated = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            elapsed_minutes = (now - updated.timestamp()) / 60
            if elapsed_minutes <= threshold_minutes:
                continue
            if self._has_recent_progress(name, runs_dir, now, grace_minutes * 60):
                continue
            signals.append(self._make_signal(
                "stuck", name,
                f"'{name}' 卡在 {status} 超过 {int(elapsed_minutes)} 分钟且无 run 进度",
                f"updated={updated_str}，阈值 {int(threshold_minutes)} 分钟",
            ))
        return signals

    def _detect_merge_streak(self, specs: dict) -> list:
        """_merge_streak 已达熔断阈值仍滞留（merge-back 反复失败）。"""
        signals = []
        threshold = int(self.admin_cfg["merge_breaker_threshold"])
        for name, entry in specs.items():
            try:
                streak = int(entry.get("_merge_streak", 0) or 0)
            except (TypeError, ValueError):
                continue
            if streak < threshold:
                continue
            status = entry.get("status")
            if status not in ("ready", "implementing", "blocked"):
                continue
            fp = entry.get("_merge_fp") or "unknown"
            signals.append(self._make_signal(
                "merge_streak", name,
                f"'{name}' merge-back 连续失败 {streak} 次已达熔断阈值仍滞留（{status}）",
                f"_merge_streak={streak}，指纹={fp}",
            ))
        return signals

    def _detect_daemon_errors(self, now: float) -> list:
        """fenixd.log 尾部连续 ERROR ≥ 阈值。"""
        log_file = self.project_root / ".fenix" / "logs" / "fenixd.log"
        if not log_file.exists():
            return []
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        # 取尾部，跳过空行，统计结尾连续 ERROR 数量
        tail = [l for l in lines[-200:] if l.strip()]
        streak = 0
        for line in reversed(tail):
            if '"level": "ERROR"' in line:
                streak += 1
            elif '"level"' in line:  # 遇到其他级别即中断连续段
                break
        if streak < DAEMON_ERROR_THRESHOLD:
            return []
        return [self._make_signal(
            "daemon_errors", None,
            f"fenixd 日志尾部连续 {streak} 条 ERROR",
            f"最近连续 ERROR ≥{DAEMON_ERROR_THRESHOLD} 条（fenixd.log 尾部）",
        )]

    # ── 信号处理：记录 + 节流 + 唤起 ────────────────────────────

    def _handle_signal(self, signal: dict):
        """处理单条信号：记录审计 + 节流判定 + 唤起 Administrator。"""
        spec = signal.get("spec")
        signal_type = signal.get("signal_type")

        # 节流：冷却窗口内同 spec 同类信号已唤起过 / 已有未处理升级告警 → 跳过唤起
        if self._throttled(spec, signal_type):
            self.logger.info(
                "admin_monitor",
                f"Signal throttled: {signal_type} for '{spec or 'daemon'}' "
                f"(cooldown {int(self.cooldown_minutes)}m)",
                {"signal": signal},
            )
            self.store.append({
                "kind": SIGNAL,
                "signal_type": signal_type,
                "spec": spec,
                "severity": signal.get("severity"),
                "description": signal.get("description"),
                "evidence": signal.get("evidence"),
                "recommended_action": signal.get("recommended_action"),
                "escalated": False,
            })
            return

        # 节流通过：先记录 signal（作为本次唤起的冷却锚点），再唤起
        signal_rec = self.store.append({
            "kind": SIGNAL,
            "signal_type": signal_type,
            "spec": spec,
            "severity": signal.get("severity"),
            "description": signal.get("description"),
            "evidence": signal.get("evidence"),
            "recommended_action": signal.get("recommended_action"),
            "escalated": True,
        })
        self.logger.warning(
            "admin_monitor",
            f"Distress detected, invoking Administrator: {signal_type} for '{spec or 'daemon'}'",
            {"signal": signal},
        )
        self._invoke_administrator(signal, signal_rec)

    def _throttled(self, spec, signal_type: str) -> bool:
        """冷却窗口内已有同信号记录，或已存在未处理升级告警 → 节流。"""
        if self.store.latest_signal(spec, signal_type, self.cooldown_minutes) is not None:
            return True
        if self.store.unhandled_for(spec, signal_type) is not None:
            return True
        return False

    # ── 兜底升级（fix-admin-self-heal） ──────────────────────────

    def _recover_orphaned_dispositions(self):
        """检测「admin 被唤起但未完成处置」（pending 无最终结果）→ 升级人工。

        admin 是 daemon 子进程，若其在处置中被 kill（daemon 重启/崩溃），不会留下
        最终 disposition、也不会走升级分支。此方法每次巡检兜底：pending 记录超时
        无最终结果 → 转为人工升级告警，保证「admin 死了也有告警」。
        """
        records = self.store.read_all()
        grace = max(self.cooldown_minutes, 1) * 60
        now = time.time()
        by_run: dict = {}
        for rec in records:
            if rec.get("kind") != DISPOSITION:
                continue
            rid = rec.get("admin_run_id")
            if not rid:
                continue
            status = rec.get("status") or rec.get("result")
            by_run.setdefault(rid, {"final": False, "rec": rec})
            if status != "pending":
                by_run[rid]["final"] = True

        for rid, info in by_run.items():
            if info["final"]:
                continue
            pending = info["rec"]
            try:
                created = datetime.fromisoformat(
                    (pending.get("created") or "").replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                continue
            if now - created.timestamp() < grace:
                continue
            spec = pending.get("spec")
            sig_type = pending.get("signal_type")
            if self.store.unhandled_for(spec, sig_type) is not None:
                continue

            # fix-graceful-shutdown-agents：先验 run 文件是否含 interrupted 标记（daemon
            # 优雅退出所致已知中断）。含标记 → 判定已知中断：终结 pending disposition 且
            # 不产生人工升级告警；无标记/文件缺失 → 维持现有"疑似 daemon 崩溃"升级兜底
            # （保守方向：宁可多告警不漏告警，files 被 prune 删除也按无标记处理）。
            if self._run_has_interrupted_marker(rid):
                self.store.append({
                    "kind": DISPOSITION,
                    "status": "interrupted",
                    "signal_type": sig_type,
                    "spec": spec,
                    "admin_run_id": rid,
                    "result": "interrupted",
                    "actions_taken": (
                        "AdminMonitor 孤儿检测：run 文件含 interrupted 标记，"
                        "判定为 daemon 优雅退出已知中断，终结该 run 且不升级人工"
                    ),
                    "description": f"Administrator 处置因 daemon 关闭被中断（run {rid}），已知中断已终结",
                })
                self.logger.info(
                    "admin_monitor",
                    f"Orphaned admin disposition marked interrupted (known shutdown): {rid}",
                )
                continue

            self.store.append(attach_trigger({
                "kind": ESCALATION,
                "signal_type": sig_type,
                "spec": spec,
                "severity": "critical",
                "description": (
                    f"Administrator 处置中断（run {rid}）：被唤起后未在 "
                    f"{int(grace / 60)} 分钟内完成处置，疑似 daemon 重启/崩溃连带杀死 "
                    f"admin，需人工介入"
                ),
                "evidence": f"pending disposition 超时无最终结果（admin_run_id={rid}）",
                "action_taken": "AdminMonitor 孤儿检测：pending 超时自动升级",
                "admin_run_id": rid,
                "recommended_action": (
                    "人工检查 daemon/AdminMonitor 状态与 .fenix/logs/supervisor.log，"
                    "确认框架是否健康运行"
                ),
            }))
            # 升级即终结：补非 pending 记录，避免 escalation 被 handled 后 unhandled_for
            # 节流失效、同一孤儿在下轮巡检再次升级造成循环告警
            self.store.append({
                "kind": DISPOSITION,
                "status": "escalated",
                "signal_type": sig_type,
                "spec": spec,
                "admin_run_id": rid,
                "result": "escalated",
                "actions_taken": "AdminMonitor 孤儿检测：pending 超时升级人工并终结该 run",
                "description": f"Administrator 处置中断已升级人工（run {rid}），pending 终结",
            })
            self.logger.warning(
                "admin_monitor",
                f"Orphaned admin disposition escalated to human: {rid}",
            )

    def _run_has_interrupted_marker(self, admin_run_id: str) -> bool:
        """检查 admin_run_id 对应的 run 产物是否含 interrupted 标记（已知 daemon 中断）。

        fix-graceful-shutdown-agents：admin agent 被 daemon 优雅退出终止时，agent_runner
        会向 `.fenix/runs/<admin_run_id>.jsonl` 追加 `{"type": "interrupted"}` 记录。孤儿
        检测据此区分"已知中断"（与 run 共存）与"疑似崩溃"（run 无标记）。run 文件被 prune
        删除或读不到标记，一律按 False（无证据 → 升级兜底，保守方向）。

        Args:
            admin_run_id: admin disposition 的 admin_run_id（形如 admin-<spec>-<ts>）。
        """
        run_file = self.project_root / ".fenix" / "runs" / f"{admin_run_id}.jsonl"
        if not run_file.is_file():
            return False
        try:
            with run_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(entry, dict) and entry.get("type") == "interrupted":
                        return True
        except OSError:
            return False
        return False

    def _detect_restart_failure(self, now: float):
        """restart_request 存在且过期 → 重启未完成 → 升级人工。

        admin 请求重启后由 supervisor 负责实际重启并清除 restart_request。
        若文件一直存在，说明 supervisor 未运行或重启失败，需人工介入。
        """
        rr = self.project_root / ".fenix" / "restart_request"
        if not rr.exists():
            return []
        try:
            mtime = rr.stat().st_mtime
        except OSError:
            return []
        if now - mtime < RESTART_REQUEST_TIMEOUT_MINUTES * 60:
            return []  # 刚请求，窗口内不升级
        if self.store.unhandled_for(None, "restart_failed") is not None:
            return []
        self.store.append({
            "kind": ESCALATION,
            "signal_type": "restart_failed",
            "spec": None,
            "severity": "critical",
            "description": (
                "daemon 重启请求未完成：.fenix/restart_request 存在超过 "
                f"{RESTART_REQUEST_TIMEOUT_MINUTES} 分钟，supervisor 未重启 daemon"
            ),
            "evidence": f"restart_request mtime={mtime}，supervisor 应清除该文件",
            "action_taken": "AdminMonitor 重启验证：请求未完成自动升级",
            "recommended_action": (
                "人工检查 supervisor 是否在运行（tmux/进程），必要时手动启动 "
                "`.fenix/bin/fenixd_supervisor.py`"
            ),
        })
        return ["restart_failed"]

    def invoke_manual(self, signal: dict):
        """手动唤起入口（fenixd 主循环拾取 .fenix/admin_invoke_request.json）。

        与自动检测共用 _invoke_administrator 的唤起+落痕路径：run_administrator
        返回后落最终 DISPOSITION（终结 run_administrator 开头落的 pending 记录），
        escalate 时落升级告警。此前手动路径直接调 run_administrator 并丢弃返回值，
        pending 永无终态、处置叙述从不入告警时间线，dashboard 上显示「处置中」
        导致用户反复手动重呼（2026-08-29 v2-cutover-main-entry 三连呼实证）。

        不检查 enabled：用户显式呼叫应始终响应（enabled 只约束自动巡检）。
        """
        self._invoke_administrator(signal, None)

    def _invoke_administrator(self, signal: dict, signal_rec: dict):
        """唤起 Administrator 处置；失败或升级时落升级告警。"""
        if self.agent_runner is None:
            self.logger.warning(
                "admin_monitor",
                "No agent_runner available, cannot invoke Administrator; escalating to human",
            )
            self.store.append(attach_trigger({
                "kind": ESCALATION,
                "signal_type": signal.get("signal_type"),
                "spec": signal.get("spec"),
                "severity": signal.get("severity"),
                "description": signal.get("description"),
                "evidence": signal.get("evidence"),
                "action_taken": "Administrator 不可用（未配置 agent_runner），未能自动处置",
                "recommended_action": signal.get("recommended_action"),
            }))
            return

        try:
            disp = self.agent_runner.run_administrator(signal)
        except Exception as e:
            self.logger.error(
                "admin_monitor",
                f"Administrator invocation failed: {e}",
                {"signal": signal},
            )
            self.store.append(attach_trigger({
                "kind": ESCALATION,
                "signal_type": signal.get("signal_type"),
                "spec": signal.get("spec"),
                "severity": signal.get("severity"),
                "description": signal.get("description"),
                "evidence": signal.get("evidence"),
                "action_taken": f"Administrator 唤起失败: {e}",
                "recommended_action": signal.get("recommended_action"),
            }))
            return

        # 处置记录（任何情况下都留痕）；落盘失败不能丢 final 判定（否则该 run
        # 的 pending 会变孤儿触发人工升级），记日志后继续
        try:
            self.store.append({
                "kind": DISPOSITION,
                "signal_type": signal.get("signal_type"),
                "spec": signal.get("spec") or disp.spec,
                "severity": signal.get("severity"),
                "description": disp.problem or signal.get("description"),
                "action_taken": disp.actions_taken,
                "result": disp.result,
                "recommended_action": disp.recommended_action,
                "summary": disp.summary,
                "admin_run_id": disp.run_id,
                "escalate": bool(disp.escalate),
            })
        except Exception as e:
            self.logger.error(
                "admin_monitor",
                f"Failed to persist administrator disposition for run {disp.run_id}: {e}",
            )

        # family_explosion 处置：Administrator「放行一次」→ 设置父 SPEC 豁免位
        # （fix-family-convergence-governor / design D4）。结构字段优先级最高；
        # 文本动作（放行 / _family_waiver / waive）兜底，兼容自由文本处置。
        self._apply_family_waiver(signal, disp)

        if disp.escalate:
            # Administrator 判定无法自主处置 → 升级人工
            self.store.append(attach_trigger({
                "kind": ESCALATION,
                "signal_type": signal.get("signal_type"),
                "spec": signal.get("spec") or disp.spec,
                "severity": signal.get("severity"),
                "description": signal.get("description"),
                "evidence": signal.get("evidence"),
                "action_taken": disp.actions_taken,
                "recommended_action": disp.recommended_action or signal.get("recommended_action"),
                "admin_run_id": disp.run_id,
            }))
            self.logger.warning(
                "admin_monitor",
                f"Administrator escalated to human: {signal.get('signal_type')} "
                f"for '{signal.get('spec') or 'daemon'}'",
            )

    # ── 辅助 ────────────────────────────────────────────────────

    def _apply_family_waiver(self, signal: dict, disp) -> None:
        """family_explosion 处置「放行一次」→ 设置父 SPEC 豁免位 _family_waiver=true。

        判定：结构字段 disp.family_waiver 为 True；或自由文本
        actions_taken/recommended_action 含显式放行语义（赋值型 _family_waiver=true、
        「设置 _family_waiver 为 true」「放行一次」等），且不含否定短语
        （未放行/不发放/不予放行…）。仅在叙述中提及豁免位字面令牌不构成放行。
        豁免位由 pm_engine 族谱门在下一轮实际创建工作开始时消费并复位（单次）。

        Args:
            signal: 本次唤起信号 dict（含 signal_type/spec）。
            disp: AdminDisposition 处置结果。
        """
        if signal.get("signal_type") != "family_explosion":
            return
        spec = signal.get("spec")
        if not spec:
            return
        text = (
            f"{(disp.actions_taken or '')}\n{(getattr(disp, 'summary', '') or '')}\n"
            f"{(disp.recommended_action or '')}"
        )
        # 否定语义优先：任何位置出现否定短语即不放行（保守方向：宁可漏放行、
        # 不可给未放行的父 SPEC 错开派生口子）。结构字段 family_waiver=True
        # 优先级最高（Administrator 结构化回填不受文本兜底影响）。
        if bool(getattr(disp, "family_waiver", False)):
            waived = True
        else:
            negated = any(n in text for n in _WAIVER_NEGATION_PHRASES)
            if negated:
                waived = False
            else:
                waived = any(
                    re.search(pattern, text) for pattern in _WAIVER_GRANT_PATTERNS
                )
                if not waived:
                    # 赋值型兜底：_family_waiver=true 须与「放行」动词同句才算
                    # 显式放行——叙述中对他族谱豁免状态的提及不构成放行。
                    waived = any(
                        _WAIVER_ASSIGN_RE.search(sent) and "放行" in sent
                        for sent in re.split(r"[。！？\n]", text)
                    )
        if not waived:
            return
        sm = self.state_machine
        if not hasattr(sm, "update_spec"):
            # 测试替身等最小状态机：仅能检测，无法落位（放行仍判定为本次已放行）
            self.logger.warning("admin_monitor", f"family_explosion 放行但状态机不支持写豁免位（spec={spec}）")
            return
        try:
            sm.update_spec(spec, {"_family_waiver": "true"})
            self.logger.info(
                "admin_monitor",
                f"family_explosion 人工放行: '{spec}' 已设置 _family_waiver=true（单次豁免）",
            )
        except Exception as e:
            self.logger.warning("admin_monitor", f"family_explosion 豁免位设置失败: {e}")

    @staticmethod
    def _spec_from_run_id(run_id: str):
        """从 run_id 还原 spec 名：匹配 <prefix><spec>-<ts> 结构。

        如 impl-myspec-1735... → myspec；planner-plan-myspec-1735... → myspec。
        无法识别返回 None。
        """
        for prefix in _RUN_PREFIXES:
            if not run_id.startswith(prefix):
                continue
            rest = run_id[len(prefix):]
            m = re.match(r"^(.*)-\d{9,10}(-a\d+)?$", rest)
            if m:
                return m.group(1)
        return None

    @staticmethod
    def _run_terminal_status(run_file: Path) -> str:
        """读取产物尾部判定终态：error / done / running / empty。

        与 dashboard.data.classify_run 同语义，避免跨层 import dashboard。
        """
        try:
            size = run_file.stat().st_size
            with run_file.open("rb") as f:
                if size > 4096:
                    f.seek(size - 4096)
                tail = f.read().decode("utf-8", "replace")
        except OSError:
            return "empty"
        last = None
        for line in tail.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                last = entry
        if not last:
            return "empty"
        t = last.get("type")
        if t == "result":
            return "done"
        if t == "error":
            return "error"
        return "running"

    def _has_recent_progress(self, spec: str, runs_dir: Path, now: float, window: float) -> bool:
        """该 spec 是否存在窗口内有写活动的 run 文件（有进度）。"""
        if not runs_dir.is_dir():
            return False
        try:
            files = list(runs_dir.glob("*.jsonl"))
        except OSError:
            return False
        for p in files:
            if self._spec_from_run_id(p.stem) != spec:
                continue
            try:
                if now - p.stat().st_mtime < window:
                    return True
            except OSError:
                continue
        return False

    # ── 状态变更历史（抖动检测） ────────────────────────────────

    def _load_history(self) -> dict:
        try:
            data = json.loads(self._history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_history(self, history: dict):
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            prefix=".admin_state_history.",
            suffix=".tmp",
            dir=str(self._history_path.parent),
        )
        tmp_path = Path(tmp)
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False)
            tmp_path.replace(self._history_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _update_history(self, specs: dict, now: float):
        """把当前快照与上次记录对比，状态变化则追加变更事件；裁剪过期条目。"""
        history = self._load_history()
        cutoff = now - 60 * 60  # 只保留最近 1 小时
        changed = False
        for name, entry in specs.items():
            status = entry.get("status")
            if status not in ("ready", "implementing"):
                continue
            rec = history.get(name)
            last_status = rec.get("last_status") if isinstance(rec, dict) else None
            changes = rec.get("changes") if isinstance(rec, dict) else []
            if last_status is not None and last_status != status:
                changes.append([now, status])
                changes = [c for c in changes if c[0] >= cutoff]
                changed = True
            elif not rec:
                changed = True
            history[name] = {"last_status": status, "changes": changes}
        # 清理不在进行中的 spec 的历史（避免文件无限膨胀）
        active = {n for n, e in specs.items() if e.get("status") in ("ready", "implementing")}
        for name in list(history.keys()):
            if name not in active:
                del history[name]
                changed = True
        if changed:
            self._save_history(history)
