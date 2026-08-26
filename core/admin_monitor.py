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

# 默认阈值（design D2）
REPEAT_FAILURE_WINDOW_MINUTES = 30
REPEAT_FAILURE_THRESHOLD = 3
FLAPPING_WINDOW_MINUTES = 10
FLAPPING_THRESHOLD = 3
DAEMON_ERROR_THRESHOLD = 3
STUCK_GRACE_MINUTES = 10  # run 文件 mtime 距现在小于此值视为"有进度"，不算卡死
RESTART_REQUEST_TIMEOUT_MINUTES = 10  # restart_request 超时未清除 → 重启失败 → 升级

# 信号 → 严重度/建议处置
SIGNAL_SEVERITY = {
    "repeated_failures": "major",
    "flapping": "major",
    "stuck": "major",
    "merge_streak": "critical",
    "blocked_stuck": "critical",
    "daemon_errors": "critical",
}
SIGNAL_RECOMMENDATION = {
    "repeated_failures": "检查重复失败的根因（如构建/测试命令错误），必要时重置 spec 状态或修复框架配置",
    "flapping": "检查 spec 状态机空转回路（ready↔implementing），修复派发/恢复逻辑或人工介入",
    "stuck": "检查卡死 Agent 子进程（kill 并按需重启），或重置 spec 状态重新调度",
    "merge_streak": "检查 merge-back 冲突根因（stash/分支冲突），清理 git 状态后重新 merge",
    "blocked_stuck": "检查 blocked 是否误置（误判派生的假 spec）或确需人工决策；清理假 spec 或重置后重新调度，必要时升级",
    "daemon_errors": "检查 fenixd 连续 ERROR 的根因，必要时重启 daemon",
}

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
        if not self.has_in_progress_specs():
            self.logger.debug("admin_monitor", "No in-progress SPECs, skipping health check")
            return []

        specs = self.state_machine.read_all()
        now = time.time()
        signals = self._detect(specs, now)

        for signal in signals:
            self._handle_signal(signal)

        # fix-admin-self-heal：孤儿处置与重启失败的兜底升级（非 per-spec 信号）
        self._recover_orphaned_dispositions()
        self._detect_restart_failure(now)
        return signals

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
            self.store.append({
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
            })
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

    def _invoke_administrator(self, signal: dict, signal_rec: dict):
        """唤起 Administrator 处置；失败或升级时落升级告警。"""
        if self.agent_runner is None:
            self.logger.warning(
                "admin_monitor",
                "No agent_runner available, cannot invoke Administrator; escalating to human",
            )
            self.store.append({
                "kind": ESCALATION,
                "signal_type": signal.get("signal_type"),
                "spec": signal.get("spec"),
                "severity": signal.get("severity"),
                "description": signal.get("description"),
                "evidence": signal.get("evidence"),
                "action_taken": "Administrator 不可用（未配置 agent_runner），未能自动处置",
                "recommended_action": signal.get("recommended_action"),
            })
            return

        try:
            disp = self.agent_runner.run_administrator(signal)
        except Exception as e:
            self.logger.error(
                "admin_monitor",
                f"Administrator invocation failed: {e}",
                {"signal": signal},
            )
            self.store.append({
                "kind": ESCALATION,
                "signal_type": signal.get("signal_type"),
                "spec": signal.get("spec"),
                "severity": signal.get("severity"),
                "description": signal.get("description"),
                "evidence": signal.get("evidence"),
                "action_taken": f"Administrator 唤起失败: {e}",
                "recommended_action": signal.get("recommended_action"),
            })
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

        if disp.escalate:
            # Administrator 判定无法自主处置 → 升级人工
            self.store.append({
                "kind": ESCALATION,
                "signal_type": signal.get("signal_type"),
                "spec": signal.get("spec") or disp.spec,
                "severity": signal.get("severity"),
                "description": signal.get("description"),
                "evidence": signal.get("evidence"),
                "action_taken": disp.actions_taken,
                "recommended_action": disp.recommended_action or signal.get("recommended_action"),
                "admin_run_id": disp.run_id,
            })
            self.logger.warning(
                "admin_monitor",
                f"Administrator escalated to human: {signal.get('signal_type')} "
                f"for '{signal.get('spec') or 'daemon'}'",
            )

    # ── 辅助 ────────────────────────────────────────────────────

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
